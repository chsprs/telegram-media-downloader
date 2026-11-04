# Telegram Media Downloader Bot

Bot Telegram ringan untuk mengunduh video dan audio dari berbagai platform sosial media (TikTok, Instagram, YouTube, Twitter/X, Facebook, SoundCloud, Reddit, Pinterest, dll.) menggunakan engine `yt-dlp`.

Didesain khusus untuk perangkat hemat daya berdaya komputasi terbatas seperti Linux ARM STB (Amlogic HG680P, H96 Max, Raspberry Pi) yang berjalan di Armbian/Debian.

---

## Fitur Utama

- **Multi-Platform**: Mendukung 1000+ situs web yang didukung oleh `yt-dlp`.
- **Full GUI (Inline Keyboard)**: Seluruh alur pakai tombol — menu, pilih format, konfirmasi, sampai batal. Tanpa perlu mengetik perintah.
- **Pratinjau Sebelum Unduh**: Kartu info (thumbnail, judul, durasi, views) + estimasi ukuran tiap format.
- **Approval Gate**: Unduhan baru jalan setelah user menekan **Setujui & Unduh**.
- **Pilihan Format Lengkap**: Video MP4 1080p / 720p / 480p / terbaik, dan audio MP3 320 / 192 / 128 kbps.
- **Progress Bar Live**: Persentase, kecepatan, dan ETA saat mengunduh.
- **Hemat Penyimpanan (Disk-Safe)**: File sementara selalu dihapus (termasuk sisa `.part`) agar eMMC/storage tidak penuh.
- **Proteksi Ukuran File**: Estimasi > 50 MB ditandai peringatan, file asli dicek ulang sebelum upload.
- **User Whitelist**: Opsi pembatasan akses (`ALLOWED_USER_IDS`).
- **Konsumsi Memori Rendah**: `pyTelegramBotAPI` (<30 MB RSS), cocok untuk STB 1 GB.

---

## Alur Pemakaian (Full GUI)

```
/start  ->  kartu menu  [Kirim Link] [Cara Pakai] [Status Bot]
   |
   +- kirim URL
   |      |
   |  probe metadata (judul, durasi, thumbnail, estimasi size)
   |      |
   |  kartu format:  Video 1080p / 720p / 480p / Terbaik
   |                  Audio MP3 320 / 192 / 128      [Batal]
   |      |
   |  kartu konfirmasi: judul . durasi . format . estimasi size
   |      [Setujui & Unduh] [Ganti Format] [Batal]
   |      |
   |  progress bar live (persen, speed, ETA)
   |      |
   +-  file terkirim -> file temp dibersihkan otomatis
```

Perintah teks (opsional):

- `/start` atau `/help` — tampilkan kartu menu.
- `/ping` — cek latensi bot.

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

### 5. Update ke Versi Terbaru

```bash
cd /opt/telegram-media-downloader
git pull
./venv/bin/pip install -r requirements.txt
sudo systemctl restart telegram-downloader.service
```

---

## Catatan Teknis

- Limit upload Bot API Telegram adalah **50 MB**. Untuk file lebih besar, gunakan format yang lebih kecil (480p / MP3 128) atau self-hosted Bot API server.
- `yt-dlp` perlu di-update berkala karena situs sumber sering berubah:
  ```bash
  ./venv/bin/pip install -U yt-dlp
  sudo systemctl restart telegram-downloader.service
  ```
- Sesi (link yang sudah dipilih) disimpan in-memory; restart service akan mengosongkannya.

---

## Lisensi

MIT License
