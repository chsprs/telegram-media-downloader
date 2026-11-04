#!/usr/bin/env python3
"""
Telegram Media Downloader Bot — full GUI flow (inline keyboard).

Alur:
  1. /start          -> kartu menu
  2. kirim link      -> probe metadata, kartu info + thumbnail
  3. pilih format    -> tombol video (1080/720/480/terbaik) & audio (MP3 320/192/128)
  4. approval        -> kartu konfirmasi (judul, durasi, format, estimasi size)
  5. unduh           -> progress bar live -> kirim file -> bersihkan disk

Ringan untuk ARM SBC / STB (yt-dlp + pyTelegramBotAPI).
"""

import os
import re
import sys
import time
import glob
import html
import logging
import urllib.request
from collections import OrderedDict

import telebot
from telebot import types
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
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN and __name__ == "__main__":
    logger.error("BOT_TOKEN tidak ditemukan! Set di file .env")
    sys.exit(1)

token_to_init = BOT_TOKEN if BOT_TOKEN and ":" in BOT_TOKEN else "123456:dummy_test_token"
bot = telebot.TeleBot(token_to_init, parse_mode="HTML")

ALLOWED_USERS_RAW = os.getenv("ALLOWED_USER_IDS", "").strip()
ALLOWED_USERS = set(int(uid.strip()) for uid in ALLOWED_USERS_RAW.split(",") if uid.strip().isdigit())

DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "/tmp/tg_media_downloader")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

MAX_TELEGRAM_FILESIZE = 50 * 1024 * 1024  # 50 MB Bot API limit
URL_REGEX = re.compile(r"https?://[^\s]+")

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
    """Cache in-memory: callback_data Telegram maksimal 64 byte."""

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
    return str(int(time.time() * 1000))[-8:]


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
def probe(url: str) -> dict:
    """Ambil metadata tanpa mengunduh."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "socket_timeout": 20,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

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
        # Link langsung (tanpa daftar format) — coba HEAD request untuk Content-Length
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

    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.extract_info(url, download=True)

    files = [f for f in glob.glob(os.path.join(DOWNLOAD_DIR, f"{req_id}_*")) if not f.endswith(".part")]
    if not files:
        raise yt_dlp.utils.DownloadError("File hasil unduhan tidak ditemukan.")
    return files[0]


def cleanup(req_id: str):
    for f in glob.glob(os.path.join(DOWNLOAD_DIR, f"{req_id}_*")):
        try:
            os.remove(f)
        except OSError:
            pass


# --- UI builders ---
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


def format_keyboard(req_id: str, est: dict) -> types.InlineKeyboardMarkup:
    def label(mode, base):
        size = est.get(mode)
        if size:
            mark = " ⚠️" if size > MAX_TELEGRAM_FILESIZE else ""
            return f"{base} · {human_size(size)}{mark}"
        return base

    mk = types.InlineKeyboardMarkup(row_width=2)
    mk.add(
        types.InlineKeyboardButton(label("v1080", "🎬 1080p"), callback_data=f"f:v1080:{req_id}"),
        types.InlineKeyboardButton(label("v720", "🎬 720p"), callback_data=f"f:v720:{req_id}"),
    )
    mk.add(
        types.InlineKeyboardButton(label("v480", "🎬 480p"), callback_data=f"f:v480:{req_id}"),
        types.InlineKeyboardButton(label("vbest", "🎬 Terbaik"), callback_data=f"f:vbest:{req_id}"),
    )
    mk.add(
        types.InlineKeyboardButton(label("a320", "🎵 MP3 320"), callback_data=f"f:a320:{req_id}"),
        types.InlineKeyboardButton(label("a192", "🎵 MP3 192"), callback_data=f"f:a192:{req_id}"),
    )
    mk.add(types.InlineKeyboardButton(label("a128", "🎵 MP3 128"), callback_data=f"f:a128:{req_id}"))
    mk.add(types.InlineKeyboardButton("❌ Batalkan", callback_data=f"x:{req_id}"))
    return mk


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
        lines.append("⚠️ <i>Estimasi melebihi limit 50 MB. Unduhan bisa gagal.</i>")
    else:
        lines.append("<i>Lanjutkan unduhan?</i>")
    return "\n".join(lines)


def approval_keyboard(req_id: str, mode: str) -> types.InlineKeyboardMarkup:
    mk = types.InlineKeyboardMarkup(row_width=2)
    mk.add(
        types.InlineKeyboardButton("✅ Setujui & Unduh", callback_data=f"ok:{mode}:{req_id}"),
        types.InlineKeyboardButton("🔙 Ganti Format", callback_data=f"back:{req_id}"),
    )
    mk.add(types.InlineKeyboardButton("❌ Batal", callback_data=f"x:{req_id}"))
    return mk


def menu_keyboard() -> types.InlineKeyboardMarkup:
    mk = types.InlineKeyboardMarkup(row_width=2)
    mk.add(
        types.InlineKeyboardButton("🔗 Kirim Link", callback_data="menu:link"),
        types.InlineKeyboardButton("ℹ️ Cara Pakai", callback_data="menu:help"),
    )
    mk.add(types.InlineKeyboardButton("📊 Status Bot", callback_data="menu:status"))
    return mk


def edit_card(chat_id: int, msg_id: int, text: str, markup=None, is_photo=True):
    """Edit caption kalau kartu foto, fallback ke edit text."""
    if is_photo:
        try:
            bot.edit_message_caption(text, chat_id=chat_id, message_id=msg_id, reply_markup=markup)
            return True
        except Exception:
            pass
    try:
        bot.edit_message_text(text, chat_id=chat_id, message_id=msg_id, reply_markup=markup,
                              disable_web_page_preview=True)
        return True
    except Exception:
        return False


def send_card(chat_id: int, caption: str, markup, thumb=None) -> int:
    """Kirim kartu (foto + caption) atau fallback text. Return message_id."""
    if thumb:
        try:
            msg = bot.send_photo(chat_id, thumb, caption=caption, reply_markup=markup)
            return msg.message_id
        except Exception:
            pass
    msg = bot.send_message(chat_id, caption, reply_markup=markup, disable_web_page_preview=True)
    return msg.message_id


# --- Handlers ---
WELCOME = (
    "<b>📥 Telegram Media Downloader</b>\n\n"
    "Unduh video / audio dari TikTok, Instagram, YouTube, X/Twitter, "
    "Facebook, SoundCloud, Reddit, dan 1000+ situs lain.\n\n"
    "<b>Alur:</b>\n"
    "1️⃣ Klik <i>Kirim Link</i> lalu kirim URL\n"
    "2️⃣ Pilih format (video / audio)\n"
    "3️⃣ Setujui unduhan\n\n"
    f"⚠️ Batas file: <b>{human_size(MAX_TELEGRAM_FILESIZE)}</b> (limit Bot API)"
)


def _deny(chat_id: int, user_id: int):
    bot.send_message(chat_id, f"🚫 Akses ditolak.\nUser ID Anda: <code>{user_id}</code>")


@bot.message_handler(commands=["start", "help"])
def cmd_start(message: types.Message):
    if not is_authorized(message.from_user.id):
        _deny(message.chat.id, message.from_user.id)
        return
    bot.reply_to(message, WELCOME, reply_markup=menu_keyboard(), disable_web_page_preview=True)


@bot.message_handler(commands=["ping"])
def cmd_ping(message: types.Message):
    t0 = time.time()
    msg = bot.reply_to(message, "Pong...")
    latency = (time.time() - t0) * 1000
    bot.edit_message_text(f"🏓 Pong! Latensi: <b>{latency:.0f} ms</b>",
                          chat_id=msg.chat.id, message_id=msg.message_id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("menu:"))
def handle_menu(call: types.CallbackQuery):
    action = call.data.split(":", 1)[1]
    bot.answer_callback_query(call.id)

    if action == "link":
        bot.send_message(call.message.chat.id, "🔗 Silakan kirim link video/audio sekarang.")
    elif action == "help":
        bot.send_message(call.message.chat.id, WELCOME, reply_markup=menu_keyboard(),
                         disable_web_page_preview=True)
    elif action == "status":
        text = (
            "📊 <b>Status Bot</b>\n\n"
            "🟢 Aktif\n"
            f"🧠 Sesi aktif: <b>{len(job_cache)}</b>\n"
            f"💾 Folder temp: <code>{DOWNLOAD_DIR}</code>\n"
            f"📦 Limit file: <b>{human_size(MAX_TELEGRAM_FILESIZE)}</b>"
        )
        bot.send_message(call.message.chat.id, text)


@bot.message_handler(func=lambda m: True)
def handle_link(message: types.Message):
    if not is_authorized(message.from_user.id):
        _deny(message.chat.id, message.from_user.id)
        return

    match = URL_REGEX.search(message.text or "")
    if not match:
        bot.reply_to(
            message,
            "⚠️ Kirim link yang valid (diawali <code>http://</code> atau <code>https://</code>).",
            reply_markup=menu_keyboard(),
        )
        return

    url = match.group(0)
    probe_msg = bot.reply_to(message, "🔍 Mengambil info media...")

    try:
        info = probe(url)
    except Exception as e:
        logger.warning("probe gagal: %s", e)
        bot.edit_message_text(
            "❌ Gagal membaca link.\n<code>{}</code>\n\n"
            "Pastikan link publik (bukan private/login-only).".format(html.escape(str(e)[:200])),
            chat_id=probe_msg.chat.id,
            message_id=probe_msg.message_id,
        )
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
        "chat_id": message.chat.id,
        "user_id": message.from_user.id,
    }
    job_cache.set(req_id, job)

    try:
        bot.delete_message(probe_msg.chat.id, probe_msg.message_id)
    except Exception:
        pass

    send_card(message.chat.id, card_caption(job), format_keyboard(req_id, job["est"]), thumb=job.get("thumb"))


@bot.callback_query_handler(func=lambda c: c.data.split(":")[0] in ("f", "back", "ok", "x"))
def handle_flow(call: types.CallbackQuery):
    if not is_authorized(call.from_user.id):
        bot.answer_callback_query(call.id, "Akses ditolak.", show_alert=True)
        return

    parts = call.data.split(":")
    action = parts[0]
    chat_id = call.message.chat.id
    msg_id = call.message.message_id
    is_photo = bool(call.message.photo)

    if action == "f":
        _, mode, req_id = parts
        job = job_cache.get(req_id)
        if not job:
            bot.answer_callback_query(call.id, "Sesi kedaluwarsa. Kirim ulang link.", show_alert=True)
            return
        job["mode"] = mode
        bot.answer_callback_query(call.id, f"Format: {FORMAT_LABEL.get(mode, mode)}")
        edit_card(chat_id, msg_id, approval_caption(job, mode), approval_keyboard(req_id, mode), is_photo)
        return

    if action == "back":
        req_id = parts[1]
        job = job_cache.get(req_id)
        if not job:
            bot.answer_callback_query(call.id, "Sesi kedaluwarsa. Kirim ulang link.", show_alert=True)
            return
        bot.answer_callback_query(call.id, "Pilih format lain.")
        edit_card(chat_id, msg_id, card_caption(job), format_keyboard(req_id, job["est"]), is_photo)
        return

    if action == "x":
        req_id = parts[1]
        job_cache.pop(req_id, None)
        bot.answer_callback_query(call.id, "Dibatalkan.")
        edit_card(
            chat_id, msg_id,
            "❌ <b>Unduhan dibatalkan.</b>\n\nKirim link baru kalau mau unduh lagi.",
            types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🏠 Menu", callback_data="menu:help")),
            is_photo,
        )
        return

    if action == "ok":
        _, mode, req_id = parts
        job = job_cache.get(req_id)
        if not job:
            bot.answer_callback_query(call.id, "Sesi kedaluwarsa. Kirim ulang link.", show_alert=True)
            return
        bot.answer_callback_query(call.id, "✅ Disetujui, mulai unduh...")
        edit_card(chat_id, msg_id,
                  f"⏳ <b>Menyiapkan unduhan...</b>\n\n{FORMAT_LABEL.get(mode, mode)}", None, is_photo)
        run_download(chat_id, req_id, job, mode)


def run_download(chat_id: int, req_id: str, job: dict, mode: str):
    title_html = html.escape(str(job.get("title") or "")[:90])
    label = FORMAT_LABEL.get(mode, mode)

    bar_msg = bot.send_message(chat_id, "⏳ Memulai...")
    state = {"last": 0.0}

    def on_progress(d):
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
            try:
                bot.edit_message_text(
                    f"⬇️ <b>Mengunduh...</b>\n{title_html}\n\n"
                    f"<code>{progress_bar(pct)}</code> {pct:5.1f}%\n"
                    f"📦 {human_size(done)} / {human_size(total) if total else '?'}\n"
                    f"⚡ {human_size(speed)}/s · ⏳ ETA {fmt_duration(eta)}",
                    chat_id=chat_id,
                    message_id=bar_msg.message_id,
                )
            except Exception:
                pass
        elif d.get("status") == "finished":
            try:
                bot.edit_message_text(
                    f"🔄 <b>Memproses file...</b>\n{title_html}\n\n"
                    f"<code>{progress_bar(100)}</code> 100%",
                    chat_id=chat_id,
                    message_id=bar_msg.message_id,
                )
            except Exception:
                pass

    try:
        file_path = download_media(job["url"], mode, req_id, on_progress=on_progress)
        size = os.path.getsize(file_path)

        if size > MAX_TELEGRAM_FILESIZE:
            bot.edit_message_text(
                f"❌ <b>File terlalu besar</b>\n{human_size(size)} melebihi limit "
                f"{human_size(MAX_TELEGRAM_FILESIZE)}.\n\nCoba format lebih kecil (mis. 480p atau MP3 128).",
                chat_id=chat_id,
                message_id=bar_msg.message_id,
            )
            return

        bot.edit_message_text(
            f"📤 <b>Mengunggah ke Telegram...</b>\n{title_html}\n💾 {human_size(size)}",
            chat_id=chat_id,
            message_id=bar_msg.message_id,
        )

        caption = f"<b>{title_html}</b>\n{label}"
        duration = int(job.get("duration") or 0)

        with open(file_path, "rb") as fh:
            if mode.startswith("a"):
                bot.send_audio(chat_id, fh, caption=caption,
                               title=str(job.get("title") or "")[:60], duration=duration or None)
            else:
                bot.send_video(chat_id, fh, caption=caption, duration=duration or None,
                               supports_streaming=True)

        # File sudah terkirim ke user -> hapus dari penyimpanan bot
        try:
            os.remove(file_path)
            logger.info("file terkirim & dihapus: %s", file_path)
        except OSError as e:
            logger.warning("gagal hapus %s: %s", file_path, e)

        try:
            bot.delete_message(chat_id, bar_msg.message_id)
        except Exception:
            pass

    except yt_dlp.utils.DownloadError as e:
        logger.warning("download gagal: %s", e)
        bot.edit_message_text(
            "❌ <b>Gagal mengunduh</b>\n<code>{}</code>".format(html.escape(str(e)[:200])),
            chat_id=chat_id,
            message_id=bar_msg.message_id,
        )
    except Exception as e:
        logger.exception("error tak terduga")
        try:
            bot.edit_message_text(
                "❌ <b>Error internal</b>\n<code>{}</code>".format(html.escape(str(e)[:200])),
                chat_id=chat_id,
                message_id=bar_msg.message_id,
            )
        except Exception:
            pass
    finally:
        cleanup(req_id)
        job_cache.pop(req_id, None)


def main():
    logger.info("Bot starting (GUI flow)...")
    bot.infinity_polling(timeout=20, long_polling_timeout=20)


if __name__ == "__main__":
    main()
