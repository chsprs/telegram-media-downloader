# Telegram Media Downloader Bot

Bot Telegram ringan untuk mengunduh video dan audio dari berbagai platform sosial media (TikTok, Instagram, YouTube, Twitter/X, Facebook, SoundCloud, Reddit, Pinterest, dll.) menggunakan engine `yt-dlp`.

Didesain khusus untuk perangkat hemat daya berdaya komputasi terbatas seperti Linux ARM STB (Amlogic HG680P, H96 Max, Raspberry Pi) yang berjalan di Armbian/Debian.

---

## Fitur Utama

- **Multi-Platform**: Mendukung 1000+ situs web yang didukung oleh `yt-dlp`.
- **Pilihan Format Interaktif**: Tombol inline untuk memilih unduhan **🎬 Video (MP4)** atau **🎵 Audio (MP3)**.
- **Hemat Penyimpanan (Disk-Safe)**: File sementara langsung dihapus setelah berhasil terkirim ke Telegram agar eMMC/storage tidak cepat penuh.
- **Proteksi Ukuran File**: Otomatis mendeteksi limit 50 MB Telegram Bot API sebelum mengirim file.
- **User Whitelist**: Opsi pembatasan akses (`ALLOWED_USER_IDS`) agar resource STB dan kuota internet tidak disalahgunakan orang lain.
- **Konsumsi Memori Rendah**: Menggunakan `pyTelegramBotAPI` yang sangat ringan (<30 MB RSS).

---

## Panduan Instalasi di HG680P (Armbian / Debian)

### 1. Clone Repositori

```bash
git clone https://github.com/chsprs/telegram-media-downloader.git /opt/telegram-media-downloader
cd /opt/telegram-media-downloader
```

### 2. Jalankan Script Installer

Script ini otomatis menginstal `ffmpeg`, `python3-venv`, dependensi Python, dan menyiapkan systemd service:

```bash
sudo ./install.sh
```

### 3. Konfigurasi Token Bot

Salin dan sesuaikan konfigurasi `.env`:

```bash
nano /opt/telegram-media-downloader/.env
```

Isi token dari [@BotFather](https://t.me/BotFather):
```env
BOT_TOKEN=1234567890:ABCdefGhIJKlmNoPQRsTUVwxyZ
ALLOWED_USER_IDS=123456789
DOWNLOAD_DIR=/tmp/tg_media_downloader
```
*(Catatan: `ALLOWED_USER_IDS` dapat dikosongkan jika ingin bot bisa digunakan publik).*

### 4. Jalankan Service

```bash
sudo systemctl start telegram-downloader.service
```

Untuk memantau log aplikasi secara realtime:

```bash
journalctl -u telegram-downloader.service -f
```

---

## Perintah Bot

- Kirim link apa saja langsung ke chat bot. Bot akan menampilkan tombol pilihan Video atau Audio MP3.
- `/start` atau `/help` - Menampilkan panduan penggunaan.
- `/ping` - Cek koneksi dan latensi bot.

---

## Lisensi

MIT License
