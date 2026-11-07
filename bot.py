#!/usr/bin/env python3
"""
Telegram Media Downloader Bot — MTProto Engine (Telethon)
Mendukung unduhan media besar hingga 1-2 GB natively via Telegram MTProto.

Alur:
  1. /start          -> kartu menu
  2. kirim link      -> probe metadata di thread pool, kartu info + thumbnail
  3. pilih format    -> tombol video (1080/720/480/terbaik) & audio (MP3 320/192/128)
  4. approval        -> kartu konfirmasi (judul, durasi, format, estimasi size)
  5. unduh           -> progress bar live -> streaming upload MTProto -> bersihkan disk
"""

import os
import re
import sys
import time
import glob
import html
import shutil
import logging
import asyncio
import threading
import urllib.request
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from telethon import TelegramClient, events, Button
from telethon.tl.types import DocumentAttributeAudio, DocumentAttributeVideo
import yt_dlp

# --- Logging ---
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


# --- .env loader (stdlib only) ---
def load_dotenv(filepath=".env"):
    if not os.path.isfile(filepath):
        return
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


load_dotenv()

# --- Config ---
API_ID = int(os.getenv("API_ID", "33432678"))
API_HASH = os.getenv("API_HASH", "e272c0676a332ac9be9d721c875d870a")
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN and __name__ == "__main__":
    logger.error("BOT_TOKEN tidak ditemukan! Set di file .env")
    sys.exit(1)

ALLOWED_USERS_RAW = os.getenv("ALLOWED_USER_IDS", "").strip()
ALLOWED_USERS = set(int(uid.strip()) for uid in ALLOWED_USERS_RAW.split(",") if uid.strip().isdigit())

# Gunakan direktori di disk eMMC, bukan /tmp (karena tmpfs RAM cuma 895MB di HG680P)
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "/opt/telegram-media-downloader/downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Batas upload default 1000 MB (1 GB), MTProto mendukung hingga 2000 MB
MAX_UPLOAD_MB = max(1, int(os.getenv("MAX_UPLOAD_MB", "1000")))
MAX_TELEGRAM_FILESIZE = MAX_UPLOAD_MB * 1024 * 1024
URL_REGEX = re.compile(r"https?://[^\s]+")

# ThreadPool bounded: STB ARM (HG680P) CPU lemah, batasi unduhan paralel
MAX_CONCURRENT_DOWNLOADS = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "2"))
_pool = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_DOWNLOADS)

# Disk guard: sisa disk minimum (MB) sebelum unduhan ditolak
MIN_FREE_DISK_MB = int(os.getenv("MIN_FREE_DISK_MB", "512"))

# Storage hygiene
PRUNE_MAX_AGE_SECONDS = int(os.getenv("PRUNE_MAX_AGE_SECONDS", "3600"))
PRUNE_INTERVAL_SECONDS = int(os.getenv("PRUNE_INTERVAL_SECONDS", "1800"))

# Inisialisasi TelegramClient Telethon
session_dir = os.path.dirname(os.path.abspath(__file__))
session_path = os.getenv("TELETHON_SESSION", os.path.join(session_dir, "bot_session"))
client = TelegramClient(session_path, API_ID, API_HASH)

FORMAT_LABEL = {
    "v1080": "🎬 Video 1080p (MP4)",
    "v720": "🎬 Video 720p (MP4)",
    "v480": "🎬 Video 480p (MP4)",
    "vbest": "🎬 Video kualitas terbaik",
    "a320": "🎵 Audio MP3 320 kbps",
    "a192": "🎵 Audio MP3 192 kbps",
    "a128": "🎵 Audio MP3 128 kbps",
}

VIDEO_SELECTOR = {
    "v1080": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
    "v720": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=720]+bestaudio/best[height<=720]/best",
    "v480": "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=480]+bestaudio/best[height<=480]/best",
    "vbest": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best",
}

AUDIO_KBPS = {"a320": 320, "a192": 192, "a128": 128}


# --- Helpers ---
class LRUCache(OrderedDict):
    """Cache in-memory untuk status request."""

    def __init__(self, capacity=200):
        super().__init__()
        self.capacity = capacity

    def get(self, key):
        if key not in self:
            return None
        self.move_to_end(key)
        return self[key]

    def set(self, key, value):
        if key in self:
            self.move_to_end(key)
        self[key] = value
        if len(self) > self.capacity:
            self.popitem(last=False)


job_cache = LRUCache(200)


def is_authorized(user_id: int) -> bool:
    if not ALLOWED_USERS:
        return True
    return user_id in ALLOWED_USERS


def human_size(num) -> str:
    num = float(num or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            txt = f"{num:.1f} {unit}"
            return txt.replace(".0 ", " ")
        num /= 1024


def fmt_duration(sec) -> str:
    sec = int(sec or 0)
    if sec <= 0:
        return "—"
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def progress_bar(pct: float, width: int = 14) -> str:
    pct = max(0.0, min(100.0, pct))
    filled = int(round(width * pct / 100))
    return "█" * filled + "░" * (width - filled)


def new_req_id() -> str:
    return uuid.uuid4().hex[:10]


def head_size(url) -> int:
    """Ambil Content-Length via HEAD request (untuk link file langsung)."""
    if not url:
        return 0
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            return int(resp.headers.get("Content-Length") or 0)
    except Exception:
        return 0


# --- yt-dlp ---
TRANSIENT_MARKERS = (
    "unable to extract", "unexpected response", "timed out", "timeout",
    "429", "too many requests", "temporarily", "connection reset",
    "connection aborted", "no video formats found", "unable to download webpage",
)


def _is_transient(exc) -> bool:
    msg = str(exc).lower()
    return any(k in msg for k in TRANSIENT_MARKERS)


def _ydl_retry(opts: dict, url: str, download: bool, attempts: int = 3, base_delay: float = 2.0):
    last = None
    for i in range(attempts):
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=download)
        except Exception as e:
            last = e
            if i == attempts - 1 or not _is_transient(e):
                raise
            time.sleep(base_delay * (i + 1))
            logger.info("yt-dlp gagal sesaat (%s) - percobaan ulang %d/%d",
                        str(e)[:60], i + 1, attempts - 1)
    raise last


def probe(url: str) -> dict:
    """Ambil metadata tanpa mengunduh."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "socket_timeout": 20,
    }
    info = _ydl_retry(opts, url, download=False)

    if info.get("entries"):
        entries = [e for e in info["entries"] if e]
        if not entries:
            raise yt_dlp.utils.DownloadError("Playlist kosong / tidak ada media.")
        info = entries[0]
    return info


def estimate_sizes(info: dict) -> dict:
    """Estimasi ukuran file per mode (byte)."""
    duration = info.get("duration") or 0
    fmts = info.get("formats") or []

    audio_best = 0
    for f in fmts:
        if f.get("vcodec") in (None, "none") and f.get("acodec") not in (None, "none"):
            sz = f.get("filesize") or f.get("filesize_approx") or 0
            if not sz and f.get("tbr") and duration:
                sz = f["tbr"] * 1000 / 8 * duration
            audio_best = max(audio_best, int(sz))

    est = {}
    video_best = 0
    for f in fmts:
        if f.get("vcodec") in (None, "none"):
            continue
        h = f.get("height") or 0
        if not h:
            continue
        sz = f.get("filesize") or f.get("filesize_approx") or 0
        if not sz and f.get("tbr") and duration:
            sz = f["tbr"] * 1000 / 8 * duration
        sz = int(sz)
        if not sz:
            continue
        video_best = max(video_best, sz)
        for mode, cap in (("v1080", 1080), ("v720", 720), ("v480", 480)):
            if h <= cap:
                est[mode] = max(est.get(mode, 0), sz + audio_best)

    if video_best:
        est["vbest"] = video_best + audio_best

    approx = info.get("filesize_approx") or info.get("filesize")
    if approx and "vbest" not in est:
        est["vbest"] = int(approx)

    if not est:
        size = head_size(info.get("url") or info.get("webpage_url"))
        if size:
            est["vbest"] = size

    for mode, kbps in AUDIO_KBPS.items():
        if duration:
            est[mode] = int(kbps * 1000 / 8 * duration)
    return est


def download_media(url: str, mode: str, req_id: str, on_progress=None) -> str:
    """Unduh sesuai mode, kembalikan path file hasil."""
    output_template = os.path.join(DOWNLOAD_DIR, f"{req_id}_%(id)s.%(ext)s")
    opts = {
        "outtmpl": output_template,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "playlist_items": "1",
        "retries": 3,
        "socket_timeout": 30,
        "progress_hooks": [on_progress] if on_progress else [],
    }

    if mode.startswith("a"):
        opts.update({
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": str(AUDIO_KBPS.get(mode, 192)),
            }],
        })
    else:
        opts["format"] = VIDEO_SELECTOR.get(mode, VIDEO_SELECTOR["vbest"])
        opts["merge_output_format"] = "mp4"

    _ydl_retry(opts, url, download=True)
    files = [
        f for f in glob.glob(os.path.join(DOWNLOAD_DIR, f"{req_id}_*"))
        if not f.endswith((".part", ".ytdl", ".temp", ".jpg", ".webp", ".png"))
    ]
    if not files:
        raise yt_dlp.utils.DownloadError("File hasil unduhan tidak ditemukan.")
    # Ambil file terbesar (hasil final merge)
    return max(files, key=os.path.getsize)


def cleanup(req_id: str):
    for f in glob.glob(os.path.join(DOWNLOAD_DIR, f"{req_id}_*")):
        try:
            os.remove(f)
        except OSError:
            pass


_active = set()
_probes_inflight = set()


def prune_stale_downloads(max_age_seconds: int = PRUNE_MAX_AGE_SECONDS) -> int:
    """Bersihkan file sisa unduhan / crash yang berumur > max_age_seconds di DOWNLOAD_DIR."""
    now = time.time()
    count = 0
    if not os.path.exists(DOWNLOAD_DIR):
        return 0
    for root_dir, _, filenames in os.walk(DOWNLOAD_DIR):
        for fn in filenames:
            if fn.split("_", 1)[0] in _active:
                continue
            path = os.path.join(root_dir, fn)
            try:
                if now - os.path.getmtime(path) > max_age_seconds:
                    os.remove(path)
                    count += 1
            except OSError:
                pass
    if count:
        logger.info("Pruned %d stale file(s) from %s", count, DOWNLOAD_DIR)
    return count


class DownloadCancelled(Exception):
    """Unduhan dihentikan: user minta stop atau disk kritis."""


_guard_disk_ts = [0.0]


def download_guard(cancel: threading.Event, why: dict):
    """Dipanggil dari progress hook: hentikan unduhan kalau dibatalkan / disk kritis."""
    if cancel is not None and cancel.is_set():
        why["why"] = "user"
        raise DownloadCancelled("dibatalkan pengguna")
    now = time.time()
    if now - _guard_disk_ts[0] < 2.0:
        return
    _guard_disk_ts[0] = now
    if shutil.disk_usage(DOWNLOAD_DIR).free < MIN_FREE_DISK_MB * 1024 * 1024:
        why["why"] = "disk"
        raise DownloadCancelled("disk hampir penuh")


def disk_check(est_bytes: int) -> str:
    """Pesan error kalau sisa disk tidak cukup; '' kalau aman."""
    free = shutil.disk_usage(DOWNLOAD_DIR).free
    need = int(est_bytes or 0) + MIN_FREE_DISK_MB * 1024 * 1024
    if free >= need:
        return ""
    return (
        f"❌ <b>Ruang disk tidak cukup</b>\n\n"
        f"Bebas: <b>{human_size(free)}</b>\n"
        f"Butuh: <b>{human_size(need)}</b>\n\n"
        f"Hapus file lain atau pilih format lebih kecil."
    )


# --- UI builders (Telethon Button) ---
def card_caption(job: dict) -> str:
    title = html.escape(str(job.get("title") or "Tanpa judul")[:120])
    uploader = html.escape(str(job.get("uploader") or "—")[:60])
    lines = [
        f"<b>{title}</b>",
        "",
        f"👤 {uploader}",
        f"⏱ Durasi: <b>{fmt_duration(job.get('duration'))}</b>",
    ]
    if job.get("view_count"):
        lines.append("👁 {} views".format(f"{job['view_count']:,}".replace(",", ".")))
    lines += ["", "👇 <b>Pilih format unduhan:</b>"]
    return "\n".join(lines)


def format_keyboard(req_id: str, est: dict):
    def label(mode, base):
        size = est.get(mode)
        if size:
            mark = " ⚠️" if size > MAX_TELEGRAM_FILESIZE else ""
            return f"{base} · {human_size(size)}{mark}"
        return base

    return [
        [
            Button.inline(label("v1080", "🎬 1080p"), f"f:v1080:{req_id}"),
            Button.inline(label("v720", "🎬 720p"), f"f:v720:{req_id}"),
        ],
        [
            Button.inline(label("v480", "🎬 480p"), f"f:v480:{req_id}"),
            Button.inline(label("vbest", "🎬 Terbaik"), f"f:vbest:{req_id}"),
        ],
        [
            Button.inline(label("a320", "🎵 MP3 320"), f"f:a320:{req_id}"),
            Button.inline(label("a192", "🎵 MP3 192"), f"f:a192:{req_id}"),
        ],
        [
            Button.inline(label("a128", "🎵 MP3 128"), f"f:a128:{req_id}"),
        ],
        [
            Button.inline("❌ Batalkan", f"x:{req_id}"),
        ],
    ]


def approval_caption(job: dict, mode: str) -> str:
    title = html.escape(str(job.get("title") or "Tanpa judul")[:120])
    est = job.get("est", {}).get(mode)
    dur = job.get("duration") or 0

    if mode.startswith("a"):
        est_txt = human_size(est) if est else "—"
    else:
        est_txt = f"≤ {human_size(est)}" if est else "—"

    lines = [
        "🧾 <b>KONFIRMASI UNDUHAN</b>",
        "",
        f"📌 <b>{title}</b>",
        f"⏱ Durasi: <b>{fmt_duration(dur)}</b>",
        f"🎛 Format: <b>{FORMAT_LABEL.get(mode, mode)}</b>",
        f"💾 Estimasi: <b>{est_txt}</b>",
        "",
    ]
    if est and est > MAX_TELEGRAM_FILESIZE:
        lines.append(f"⚠️ <i>Estimasi melebihi batas {human_size(MAX_TELEGRAM_FILESIZE)}. Unduhan bisa gagal.</i>")
    else:
        lines.append("<i>Lanjutkan unduhan?</i>")
    return "\n".join(lines)


def approval_keyboard(req_id: str, mode: str):
    return [
        [Button.inline("✅ Setujui & Unduh", f"ok:{mode}:{req_id}")],
        [Button.inline("🔙 Ganti Format", f"back:{req_id}"), Button.inline("❌ Batal", f"x:{req_id}")],
    ]


def menu_keyboard():
    return [
        [Button.inline("🔗 Kirim Link", "menu:link"), Button.inline("ℹ️ Cara Pakai", "menu:help")],
        [Button.inline("📊 Status Bot", "menu:status")],
    ]


def menu_markup():
    return [[Button.inline("🏠 Menu", "menu:help")]]


def stop_keyboard(req_id: str):
    return [[Button.inline("⏹ Batalkan unduhan", f"stop:{req_id}")]]


async def edit_card(chat_id: int, msg_id: int, text: str, buttons=None):
    try:
        await client.edit_message(chat_id, msg_id, text=text, buttons=buttons, parse_mode="html", link_preview=False)
        return True
    except Exception as e:
        logger.debug("edit_card gagal: %s", e)
        return False


async def send_card(chat_id: int, caption: str, buttons, thumb=None) -> int:
    if thumb:
        try:
            msg = await client.send_file(chat_id, thumb, caption=caption, buttons=buttons, parse_mode="html")
            return msg.id
        except Exception:
            pass
    msg = await client.send_message(chat_id, caption, buttons=buttons, parse_mode="html", link_preview=False)
    return msg.id


async def update_card(job: dict, text: str, buttons=None):
    msg_id = job.get("card_msg_id")
    if not msg_id:
        return
    await edit_card(job["chat_id"], msg_id, text, buttons)


# --- Handlers ---
WELCOME = (
    "<b>📥 Telegram Media Downloader (MTProto Engine)</b>\n\n"
    "Unduh video / audio dari TikTok, Instagram, YouTube, X/Twitter, "
    "Facebook, SoundCloud, Reddit, dan 1000+ situs lain.\n\n"
    "<b>Alur:</b>\n"
    "1️⃣ Klik <i>Kirim Link</i> lalu kirim URL\n"
    "2️⃣ Pilih format (video / audio)\n"
    "3️⃣ Setujui unduhan\n\n"
    f"📦 Batas file: <b>{human_size(MAX_TELEGRAM_FILESIZE)}</b> (didukung MTProto s.d 2 GB)"
)


@client.on(events.NewMessage(pattern=r"^/(start|help)"))
async def cmd_start(event):
    user_id = event.sender_id
    if not is_authorized(user_id):
        await event.reply(f"🚫 Akses ditolak.\nUser ID Anda: <code>{user_id}</code>", parse_mode="html")
        return
    await event.reply(WELCOME, buttons=menu_keyboard(), parse_mode="html", link_preview=False)


@client.on(events.NewMessage(pattern=r"^/ping"))
async def cmd_ping(event):
    t0 = time.time()
    msg = await event.reply("Pong...")
    lat = (time.time() - t0) * 1000
    await msg.edit(f"🏓 Pong! Latensi: <b>{lat:.0f} ms</b>", parse_mode="html")


@client.on(events.CallbackQuery(pattern=r"^menu:"))
async def handle_menu(event):
    data = event.data.decode("utf-8")
    action = data.split(":", 1)[1]
    await event.answer()
    chat_id = event.chat_id

    if action == "link":
        await client.send_message(chat_id, "🔗 Silakan kirim link video/audio sekarang.")
    elif action == "help":
        await client.send_message(chat_id, WELCOME, buttons=menu_keyboard(), parse_mode="html", link_preview=False)
    elif action == "status":
        free_disk = shutil.disk_usage(DOWNLOAD_DIR).free
        text = (
            "📊 <b>Status Bot (MTProto Engine)</b>\n\n"
            "🟢 Aktif (Telethon MTProto Native)\n"
            f"🧠 Sesi aktif: <b>{len(job_cache)}</b>\n"
            f"💾 Folder unduhan: <code>{DOWNLOAD_DIR}</code>\n"
            f"💽 Sisa disk: <b>{human_size(free_disk)}</b>\n"
            f"📦 Batas upload: <b>{human_size(MAX_TELEGRAM_FILESIZE)}</b>"
        )
        await client.send_message(chat_id, text, parse_mode="html")


@client.on(events.NewMessage(func=lambda e: not (e.raw_text or "").startswith("/")))
async def handle_link(event):
    user_id = event.sender_id
    if not is_authorized(user_id):
        await event.reply(f"🚫 Akses ditolak.\nUser ID Anda: <code>{user_id}</code>", parse_mode="html")
        return

    match = URL_REGEX.search(event.raw_text or "")
    if not match:
        return

    url = match.group(0).rstrip(".,);:!?\"'”’>")
    if user_id in _probes_inflight:
        await event.reply("⏳ Masih memproses permintaan sebelumnya. Tunggu sampai kartunya muncul.")
        return

    probe_msg = await event.reply("🔍 Mengambil info media...")
    _probes_inflight.add(user_id)
    asyncio.create_task(_probe_and_send(event.chat_id, user_id, url, probe_msg.id))


async def _probe_and_send(chat_id: int, user_id: int, url: str, probe_msg_id: int):
    loop = asyncio.get_running_loop()
    try:
        try:
            info = await loop.run_in_executor(_pool, probe, url)
        except Exception as e:
            logger.warning("probe gagal: %s", e)
            err_text = (
                f"❌ Gagal membaca link.\n<code>{html.escape(str(e)[:200])}</code>\n\n"
                "Pastikan link publik (bukan private/login-only)."
            )
            await client.edit_message(chat_id, probe_msg_id, err_text, parse_mode="html")
            return

        req_id = new_req_id()
        job = {
            "url": url,
            "title": info.get("title") or info.get("description") or "Tanpa judul",
            "uploader": info.get("uploader") or info.get("channel") or info.get("uploader_id"),
            "duration": info.get("duration") or 0,
            "view_count": info.get("view_count") or 0,
            "thumb": info.get("thumbnail"),
            "est": estimate_sizes(info),
            "chat_id": chat_id,
            "user_id": user_id,
        }
        job_cache.set(req_id, job)

        try:
            await client.delete_messages(chat_id, probe_msg_id)
        except Exception:
            pass

        job["card_msg_id"] = await send_card(
            chat_id, card_caption(job), format_keyboard(req_id, job["est"]), thumb=job.get("thumb")
        )
    except Exception as e:
        logger.exception("probe worker error")
        try:
            await client.edit_message(
                chat_id, probe_msg_id, f"❌ <b>Error internal</b>\n<code>{html.escape(str(e)[:150])}</code>", parse_mode="html"
            )
        except Exception:
            pass
    finally:
        _probes_inflight.discard(user_id)


@client.on(events.CallbackQuery(pattern=r"^(f|back|ok|x|stop):"))
async def handle_flow(event):
    data = event.data.decode("utf-8")
    parts = data.split(":")
    action = parts[0]
    user_id = event.sender_id
    chat_id = event.chat_id
    msg_id = event.message_id

    if not is_authorized(user_id):
        await event.answer("Akses ditolak.", alert=True)
        return

    if action == "f":
        _, mode, req_id = parts
        job = job_cache.get(req_id)
        if not job:
            await event.answer("Sesi kedaluwarsa. Kirim ulang link.", alert=True)
            return
        job["mode"] = mode
        await event.answer(f"Format: {FORMAT_LABEL.get(mode, mode)}")
        await edit_card(chat_id, msg_id, approval_caption(job, mode), approval_keyboard(req_id, mode))
        return

    if action == "back":
        req_id = parts[1]
        job = job_cache.get(req_id)
        if not job:
            await event.answer("Sesi kedaluwarsa. Kirim ulang link.", alert=True)
            return
        await event.answer("Pilih format lain.")
        await edit_card(chat_id, msg_id, card_caption(job), format_keyboard(req_id, job["est"]))
        return

    if action == "x":
        req_id = parts[1]
        job = job_cache.pop(req_id, None) or {}
        cancel = job.get("cancel")
        if cancel is not None:
            cancel.set()
        cleanup(req_id)
        await event.answer("Dibatalkan.")
        title = html.escape(str(job.get("title") or "Tanpa judul")[:120])
        await edit_card(
            chat_id, msg_id,
            f"❌ <b>Dibatalkan</b>\n\n📌 {title}\n\nKirim link baru kalau mau unduh lagi.",
            menu_markup(),
        )
        return

    if action == "stop":
        req_id = parts[1]
        job = job_cache.get(req_id)
        if not job or not job.get("cancel"):
            await event.answer("Unduhan sudah selesai / tidak aktif.")
            return
        job["cancel"].set()
        await event.answer("⏹ Menghentikan unduhan...")
        return

    if action == "ok":
        _, mode, req_id = parts
        job = job_cache.get(req_id)
        if not job:
            await event.answer("Sesi kedaluwarsa. Kirim ulang link.", alert=True)
            return
        if job.get("busy"):
            await event.answer("Unduhan ini sedang berjalan.", alert=True)
            return
        job["busy"] = True
        warn = disk_check(job.get("est", {}).get(mode) or 0)
        if warn:
            job["busy"] = False
            await event.answer("Ruang disk tidak cukup.", alert=True)
            await update_card(job, warn, menu_markup())
            return
        await event.answer("✅ Disetujui, mulai unduh...")
        await edit_card(chat_id, msg_id, f"⏳ <b>Menyiapkan unduhan...</b>\n\n{FORMAT_LABEL.get(mode, mode)}", None)
        asyncio.create_task(run_download(chat_id, req_id, job, mode))


async def run_download(chat_id: int, req_id: str, job: dict, mode: str):
    title_html = html.escape(str(job.get("title") or "")[:90])
    label = FORMAT_LABEL.get(mode, mode)
    bar_msg = await client.send_message(chat_id, "⏳ Memulai...", buttons=stop_keyboard(req_id))
    state = {"last": 0.0, "last_text": ""}
    cancel = job.setdefault("cancel", threading.Event())
    why = {}
    _active.add(req_id)

    loop = asyncio.get_running_loop()

    def on_progress(d):
        download_guard(cancel, why)
        if d.get("status") == "downloading":
            now = time.time()
            if now - state["last"] < 3:
                return
            state["last"] = now
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            pct = (done / total * 100) if total else 0
            speed = d.get("speed") or 0
            eta = d.get("eta") or 0
            text = (
                f"⬇️ <b>Mengunduh...</b>\n{title_html}\n\n"
                f"<code>{progress_bar(pct)}</code> {pct:5.1f}%\n"
                f"📦 {human_size(done)} / {human_size(total) if total else '?'}\n"
                f"⚡ {human_size(speed)}/s · ⏳ ETA {fmt_duration(eta)}"
            )
            if text == state.get("last_text"):
                return
            state["last_text"] = text
            asyncio.run_coroutine_threadsafe(
                client.edit_message(chat_id, bar_msg.id, text, buttons=stop_keyboard(req_id), parse_mode="html"),
                loop,
            )
        elif d.get("status") == "finished":
            text = (
                f"🔄 <b>Memproses file...</b>\n{title_html}\n\n"
                f"<code>{progress_bar(100)}</code> 100%"
            )
            if text == state.get("last_text"):
                return
            state["last_text"] = text
            asyncio.run_coroutine_threadsafe(
                client.edit_message(chat_id, bar_msg.id, text, buttons=stop_keyboard(req_id), parse_mode="html"),
                loop,
            )

    try:
        file_path = await loop.run_in_executor(_pool, download_media, job["url"], mode, req_id, on_progress)
        if cancel.is_set():
            raise DownloadCancelled("dibatalkan pengguna")

        size = os.path.getsize(file_path)
        if size > MAX_TELEGRAM_FILESIZE:
            await client.edit_message(
                chat_id, bar_msg.id,
                f"❌ <b>File terlalu besar</b>\n{human_size(size)} melebihi batas {human_size(MAX_TELEGRAM_FILESIZE)}.\n\nCoba format lebih kecil.",
                parse_mode="html",
            )
            await update_card(job, f"❌ <b>Gagal</b>\n\n📌 {title_html}\n\nFile terlalu besar ({human_size(size)}).\n\nKirim link baru.", menu_markup())
            return

        await client.edit_message(
            chat_id, bar_msg.id,
            f"📤 <b>Mengunggah ke Telegram (MTProto)...</b>\n{title_html}\n💾 {human_size(size)}",
            parse_mode="html",
        )

        caption = f"<b>{title_html}</b>\n{label}"
        duration = int(job.get("duration") or 0)

        # Upload progress callback
        last_up = [0.0]

        def upload_callback(current, total):
            now = time.time()
            if now - last_up[0] < 3:
                return
            last_up[0] = now
            pct = (current / total * 100) if total else 0
            up_text = (
                f"📤 <b>Mengunggah ke Telegram (MTProto)...</b>\n{title_html}\n\n"
                f"<code>{progress_bar(pct)}</code> {pct:5.1f}%\n"
                f"📦 {human_size(current)} / {human_size(total)}"
            )
            asyncio.run_coroutine_threadsafe(
                client.edit_message(chat_id, bar_msg.id, up_text, parse_mode="html"),
                loop,
            )

        if mode.startswith("a"):
            raw_title = str(job.get("title") or "")
            audio_title = " ".join(raw_title.split())[:60]
            attr = [DocumentAttributeAudio(duration=duration, title=audio_title, performer=str(job.get("uploader") or ""))]
            await client.send_file(
                chat_id, file_path, caption=caption, parse_mode="html",
                attributes=attr, progress_callback=upload_callback
            )
        else:
            attr = [DocumentAttributeVideo(duration=duration, w=0, h=0, supports_streaming=True)]
            await client.send_file(
                chat_id, file_path, caption=caption, parse_mode="html",
                attributes=attr, supports_streaming=True, progress_callback=upload_callback
            )

        # HAPUS FILE SEGERA SETELAH DIUNGGAH KE USER
        try:
            os.remove(file_path)
            logger.info("file terkirim & langsung dihapus dari disk: %s", file_path)
        except OSError as e:
            logger.warning("gagal hapus %s: %s", file_path, e)

        try:
            await client.delete_messages(chat_id, bar_msg.id)
        except Exception:
            pass

        # Update kartu asal jadi sukses
        text = (
            f"✅ <b>Terkirim</b>\n\n"
            f"📌 {title_html}\n{label}\n💾 {human_size(size)}\n\n"
            f"Kirim link baru untuk unduh lagi."
        )
        await update_card(job, text, menu_markup())

    except DownloadCancelled:
        reason = why.get("why", "user")
        if reason == "disk":
            await client.edit_message(
                chat_id, bar_msg.id, f"❌ <b>Disk penuh</b>\n\n📌 {title_html}", parse_mode="html"
            )
            await update_card(job, f"❌ <b>Gagal</b>\n\n📌 {title_html}\n\nDisk hampir penuh.", menu_markup())
        else:
            await client.edit_message(
                chat_id, bar_msg.id, f"⏹ <b>Dibatalkan</b>\n\n📌 {title_html}", parse_mode="html"
            )
            await update_card(job, f"❌ <b>Dibatalkan</b>\n\n📌 {title_html}\n\nKirim link baru.", menu_markup())
        return

    except yt_dlp.utils.DownloadError as e:
        logger.warning("download gagal: %s", e)
        error_txt = str(e)[:150]
        await client.edit_message(
            chat_id, bar_msg.id, f"❌ <b>Gagal mengunduh</b>\n<code>{html.escape(error_txt)}</code>", parse_mode="html"
        )
        await update_card(job, f"❌ <b>Gagal</b>\n\n📌 {title_html}\n\n{error_txt}\n\nKirim link baru.", menu_markup())
    except Exception as e:
        logger.exception("error tak terduga")
        error_txt = str(e)[:150]
        try:
            await client.edit_message(
                chat_id, bar_msg.id, f"❌ <b>Error internal</b>\n<code>{html.escape(error_txt)}</code>", parse_mode="html"
            )
        except Exception:
            pass
        await update_card(job, f"❌ <b>Error</b>\n\n📌 {title_html}\n\n{error_txt}\n\nKirim link baru.", menu_markup())
    finally:
        job["busy"] = False
        cleanup(req_id)
        _active.discard(req_id)
        job_cache.pop(req_id, None)


def startup_cleanup() -> int:
    """Bot baru start = tidak ada unduhan hidup, bersihkan semua sisa crash/run sebelumnya."""
    return prune_stale_downloads(0)


async def _prune_loop():
    while True:
        await asyncio.sleep(PRUNE_INTERVAL_SECONDS)
        try:
            prune_stale_downloads(PRUNE_MAX_AGE_SECONDS)
        except Exception:
            logger.exception("prune periodik gagal")


async def main():
    logger.info("Bot starting with MTProto Telethon engine (limit %s)...", human_size(MAX_TELEGRAM_FILESIZE))
    pruned = startup_cleanup()
    if pruned:
        logger.info("Startup hygiene: %d file sisa dihapus.", pruned)
    asyncio.create_task(_prune_loop())
    await client.start(bot_token=BOT_TOKEN)
    logger.info("Telethon MTProto client connected and polling events.")
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
