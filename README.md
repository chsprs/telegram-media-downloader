# Telegram Media Downloader Bot

Bot Telegram untuk mengunduh **video / audio** dari link sosial media (TikTok, Instagram, YouTube, X/Twitter, Facebook, SoundCloud, Reddit, dll). Semua pakai tombol — engine `yt-dlp`, ringan untuk STB/ARM (RAM < 30 MB).

## Fungsi

- Kirim link → bot tampilkan kartu info (thumbnail, judul, durasi) + estimasi ukuran
- Pilih format: **Video MP4** 1080p / 720p / 480p / terbaik, atau **Audio MP3** 320 / 192 / 128 kbps
- **Konfirmasi dulu** sebelum unduh (`Setujui & Unduh`), ada progress bar (persen, speed, ETA)
- File dikirim ke chat, file sementara langsung dihapus
- Batas upload Telegram **50 MB** — format yang terlalu besar ditandai ⚠️

## Instalasi

```bash
git clone https://github.com/chsprs/telegram-media-downloader.git /opt/telegram-media-downloader
cd /opt/telegram-media-downloader
sudo ./install.sh
```

Installer akan:

1. Install `python3`, `venv`, `ffmpeg`
2. Minta **BOT_TOKEN** dari [@BotFather](https://t.me/BotFather) → langsung diverifikasi ke Telegram
3. Tanya whitelist user ID (kosongkan = publik)
4. Tulis `.env` (permission 600), daftarkan systemd, jalankan bot

Selesai. Bot langsung aktif, link `t.me/<bot_anda>` ditampilkan di akhir.

**Non-interaktif (VPS/automation):**

```bash
sudo BOT_TOKEN="8123456789:AAE..." ALLOWED_USER_IDS="123456789" ./install.sh
```

## Kontrol Bot dari Terminal

Setelah install, ada perintah singkat **`tdl`** (tidak perlu sudo — otomatis minta password):

```bash
tdl on         # nyalakan bot
tdl off        # matikan bot
tdl restart    # restart
tdl status     # cek nyala/mati + autostart
tdl log        # log realtime (Ctrl+C keluar)
tdl update     # update bot + yt-dlp, lalu restart
tdl token      # edit token / whitelist, lalu restart
tdl help       # daftar perintah
```

Alias pendek juga jalan: `tdl start`, `tdl stop`, `tdl rs`, `tdl st`, `tdl l`, `tdl up`.

## Pemakaian

1. Buka bot → `/start`
2. Kirim link video/audio
3. Pilih format (tombol sudah ada estimasi size)
4. Tekan **✅ Setujui & Unduh** — tunggu progress selesai, file dikirim
5. Salah pilih? **🔙 Ganti Format** atau **❌ Batal**

Perintah: `/start` (menu) · `/ping` (cek bot hidup)

## Update & Perbaikan

```bash
tdl update     # update bot + yt-dlp, lalu restart otomatis
```

Kalau ada situs yang gagal diunduh, itu hampir selalu karena `yt-dlp` ketinggalan versi — `tdl update` sudah mengurus itu.

## Konfigurasi `.env`

```env
BOT_TOKEN=8123456789:AAE...
ALLOWED_USER_IDS=123456789      # kosong = publik, pisah koma untuk beberapa user
DOWNLOAD_DIR=/tmp/tg_media_downloader
```

## Lisensi

MIT
