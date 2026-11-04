#!/usr/bin/env python3
"""
Telegram Media Downloader Bot
Lightweight media downloader using yt-dlp and pyTelegramBotAPI.
Optimized for low-resource environments (ARM SBC / STB).
"""

import os
import re
import sys
import time
import glob
import logging
import tempfile
from collections import OrderedDict

import telebot
from telebot import types
import yt_dlp

# --- Logging Setup ---
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Simple .env loader (stdlib only) ---
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
    logger.error("BOT_TOKEN not found! Please set it in .env")
    sys.exit(1)

# Fallback dummy token for importing/testing
token_to_init = BOT_TOKEN if BOT_TOKEN and ":" in BOT_TOKEN else "123456:dummy_test_token"
bot = telebot.TeleBot(token_to_init, parse_mode="HTML")

ALLOWED_USERS_RAW = os.getenv("ALLOWED_USER_IDS", "").strip()
ALLOWED_USERS = set(int(uid.strip()) for uid in ALLOWED_USERS_RAW.split(",") if uid.strip().isdigit())

DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "/tmp/tg_media_downloader")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

MAX_TELEGRAM_FILESIZE = 50 * 1024 * 1024  # 50MB Bot API limit

# ponytail: simple LRU memory cache for URL IDs to stay within Telegram 64-byte callback limit.
# Upgrade to SQLite if bot requires persistence across restarts.
class LRUCache(OrderedDict):
    def __init__(self, capacity=500):
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

url_cache = LRUCache(500)

# URL regex
URL_REGEX = re.compile(r"https?://[^\s]+")

def is_authorized(user_id: int) -> bool:
    if not ALLOWED_USERS:
        return True
    return user_id in ALLOWED_USERS

@bot.message_handler(commands=["start", "help"])
def cmd_start(message: types.Message):
    user_id = message.from_user.id
    if not is_authorized(user_id):
        bot.reply_to(message, f"Akses ditolak. User ID Anda: <code>{user_id}</code>")
        return

    text = (
        "<b>Telegram Media Downloader</b>\n\n"
        "Kirim link video/audio dari sosial media (TikTok, Instagram, YouTube, X/Twitter, FB, dll).\n"
        "Maksimal ukuran file: <b>50 MB</b> (limit Bot API Telegram).\n\n"
        "Perintah:\n"
        "/ping - Cek status bot"
    )
    bot.reply_to(message, text)

@bot.message_handler(commands=["ping"])
def cmd_ping(message: types.Message):
    start = time.time()
    msg = bot.reply_to(message, "Pong...")
    latency = (time.time() - start) * 1000
    bot.edit_message_text(f"Pong! Latensi: {latency:.1f} ms", chat_id=msg.chat.id, message_id=msg.message_id)

@bot.message_handler(func=lambda msg: True)
def handle_text(message: types.Message):
    user_id = message.from_user.id
    if not is_authorized(user_id):
        bot.reply_to(message, f"Akses ditolak. User ID Anda: <code>{user_id}</code>")
        return

    text = message.text or ""
    match = URL_REGEX.search(text)
    if not match:
        bot.reply_to(message, "Kirimkan link URL yang valid (awali dengan http:// atau https://).")
        return

    url = match.group(0)
    req_id = str(int(time.time() * 1000))[-8:]  # 8-char unique ID
    url_cache.set(req_id, url)

    # Inline keyboard selection
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🎬 Video", callback_data=f"dl:v:{req_id}"),
        types.InlineKeyboardButton("🎵 Audio (MP3)", callback_data=f"dl:a:{req_id}")
    )

    bot.reply_to(
        message,
        "Pilih format yang ingin diunduh:",
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("dl:"))
def handle_download_callback(call: types.CallbackQuery):
    user_id = call.from_user.id
    if not is_authorized(user_id):
        bot.answer_callback_query(call.id, "Akses ditolak.", show_alert=True)
        return

    parts = call.data.split(":")
    if len(parts) != 3:
        bot.answer_callback_query(call.id, "Data callback tidak valid.")
        return

    mode, req_id = parts[1], parts[2]
    url = url_cache.get(req_id)
    if not url:
        bot.answer_callback_query(call.id, "Link sudah kedaluwarsa. Silakan kirim ulang link.", show_alert=True)
        return

    bot.answer_callback_query(call.id, "Memproses unduhan...")

    status_msg = bot.edit_message_text(
        "⏳ Sedang mengambil info & mengunduh media...",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id
    )

    is_audio = (mode == "a")
    output_template = os.path.join(DOWNLOAD_DIR, f"{req_id}_%(id)s.%(ext)s")

    ydl_opts = {
        "outtmpl": output_template,
        "max_filesize": MAX_TELEGRAM_FILESIZE,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": False,
        "noplaylist": True,
        "playlist_items": "1",
    }

    if is_audio:
        ydl_opts.update({
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]
        })
    else:
        # Prefer MP4 under 50MB
        ydl_opts.update({
            "format": "best[ext=mp4][filesize<=50M]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[filesize<=50M]/best"
        })

    downloaded_files = []
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "Media")
            duration = info.get("duration", 0)

        # Locate downloaded file(s)
        pattern = os.path.join(DOWNLOAD_DIR, f"{req_id}_*")
        downloaded_files = glob.glob(pattern)

        if not downloaded_files:
            bot.edit_message_text(
                "❌ Gagal mengunduh media atau format tidak ditemukan.",
                chat_id=call.message.chat.id,
                message_id=status_msg.message_id
            )
            return

        file_path = downloaded_files[0]
        file_size = os.path.getsize(file_path)

        if file_size > MAX_TELEGRAM_FILESIZE:
            size_mb = file_size / (1024 * 1024)
            bot.edit_message_text(
                f"❌ Ukuran file terlalu besar ({size_mb:.1f} MB). Batas Bot API Telegram adalah 50 MB.",
                chat_id=call.message.chat.id,
                message_id=status_msg.message_id
            )
            return

        bot.edit_message_text(
            "📤 Mengunggah ke Telegram...",
            chat_id=call.message.chat.id,
            message_id=status_msg.message_id
        )

        with open(file_path, "rb") as media_file:
            caption = f"<b>{title}</b>"
            if is_audio:
                bot.send_audio(
                    chat_id=call.message.chat.id,
                    audio=media_file,
                    caption=caption,
                    title=title,
                    duration=duration
                )
            else:
                bot.send_video(
                    chat_id=call.message.chat.id,
                    video=media_file,
                    caption=caption,
                    duration=duration,
                    supports_streaming=True
                )

        # Cleanup status message
        try:
            bot.delete_message(call.message.chat.id, status_msg.message_id)
        except Exception:
            pass

    except yt_dlp.utils.DownloadError as de:
        err_msg = str(de)
        if "File is larger than max-filesize" in err_msg:
            bot.edit_message_text(
                "❌ Ukuran media melebihi batas 50 MB.",
                chat_id=call.message.chat.id,
                message_id=status_msg.message_id
            )
        else:
            logger.error("yt-dlp error: %s", de)
            bot.edit_message_text(
                f"❌ Gagal mengunduh: Link tidak didukung atau konten privat.\n<code>{err_msg[:200]}</code>",
                chat_id=call.message.chat.id,
                message_id=status_msg.message_id
            )
    except Exception as e:
        logger.exception("Unexpected error:")
        bot.edit_message_text(
            f"❌ Terjadi kesalahan internal: {str(e)[:200]}",
            chat_id=call.message.chat.id,
            message_id=status_msg.message_id
        )
    finally:
        # Ensure disk space is always freed (including .part/.temp files)
        for f in glob.glob(os.path.join(DOWNLOAD_DIR, f"{req_id}_*")):
            try:
                if os.path.exists(f):
                    os.remove(f)
            except OSError:
                pass

def main():
    logger.info("Bot starting...")
    bot.infinity_polling(timeout=20, long_polling_timeout=20)

if __name__ == "__main__":
    main()
