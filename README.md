# Telegram Media Downloader Bot

Bot Telegram untuk mengunduh **video / audio** dari link sosial media (TikTok, Instagram, YouTube, X/Twitter, Facebook, SoundCloud, Reddit, dll). Semua pakai tombol — engine `yt-dlp`, ringan untuk STB/ARM (RAM < 30 MB).

## Fungsi

- Kirim link → bot tampilkan kartu info (thumbnail, judul, durasi) + estimasi ukuran
- Pilih format: **Video MP4** 1080p / 720p / 480p / terbaik, atau **Audio MP3** 320 / 192 / 128 kbps
- **Konfirmasi dulu** sebelum unduh, ada progress bar (persen, speed, ETA)
- File dikirim ke chat, file sementara langsung dihapus
- Batas upload Telegram **50 MB** — format yang terlalu besar ditandai ⚠️

## Instalasi

```bash
git clone https://github.com/chsprs/telegram-media-downloader.git /opt/telegram-media-downloader
cd /opt/telegram-media-downloader
sudo ./install.sh
```

Installer akan install `python3`+`venv`+`ffmpeg`, minta **BOT_TOKEN** dari [@BotFather](https://t.me/BotFather) (langsung diverifikasi ke Telegram), tanya whitelist user ID (kosong = publik), tulis `.env` (600), lalu daftarkan systemd dan jalankan bot.

Non-interaktif:

```bash
sudo BOT_TOKEN="8123456789:AAE..." ALLOWED_USER_IDS="123456789" ./install.sh
```

## Command

Terminal (tanpa sudo, otomatis minta password):

| Command | Fungsi |
|---|---|
| `tdl on` | nyalakan bot |
| `tdl off` | matikan bot |
| `tdl restart` | restart bot |
| `tdl status` | cek nyala/mati + autostart |
| `tdl log` | log realtime (Ctrl+C keluar) |
| `tdl update` | update bot + yt-dlp, lalu restart |
| `tdl token` | edit token / whitelist, lalu restart |
| `tdl help` | daftar command |

Alias: `tdl start` · `tdl stop` · `tdl rs` · `tdl st` · `tdl l` · `tdl up`

Di chat bot: `/start` (menu) · `/ping` (cek bot hidup)

## Pemakaian

1. Buka bot → `/start`
2. Kirim link video/audio
3. Pilih format (tombol sudah ada estimasi size)
4. Tekan **✅ Setujui & Unduh** — tunggu progress selesai, file dikirim
5. Salah pilih? **🔙 Ganti Format** atau **❌ Batal**

## Konfigurasi `.env`

```env
BOT_TOKEN=8123456789:AAE...
ALLOWED_USER_IDS=123456789      # kosong = publik, pisah koma untuk beberapa user
DOWNLOAD_DIR=/tmp/tg_media_downloader
```

## Lisensi

MIT
