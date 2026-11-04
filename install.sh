#!/usr/bin/env bash
set -e

# Telegram Media Downloader - Installer Script for Debian / Armbian (HG680P)

INSTALL_DIR="/opt/telegram-media-downloader"
SERVICE_NAME="telegram-downloader.service"

if [ "$(id -u)" -ne 0 ]; then
    echo "Harap jalankan script ini sebagai root (sudo ./install.sh)"
    exit 1
fi

echo "==> 1. Memeriksa & menginstall dependensi sistem (python3, venv, ffmpeg)..."
apt-get update -y
apt-get install -y python3 python3-venv ffmpeg

echo "==> 2. Menyiapkan direktori aplikasi di $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"
cp -ru ./* "$INSTALL_DIR/" || cp -r ./* "$INSTALL_DIR/"
cd "$INSTALL_DIR"

echo "==> 3. Menyiapkan Python virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

echo "==> 4. Menyiapkan file konfigurasi .env..."
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo ""
    echo "=========================================================="
    echo "PERHATIAN: Silakan edit $INSTALL_DIR/.env dan masukkan BOT_TOKEN Anda:"
    echo "nano $INSTALL_DIR/.env"
    echo "=========================================================="
    echo ""
fi

echo "==> 5. Mendaftarkan systemd service..."
cp telegram-downloader.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

echo ""
echo "Instalasi selesai!"
echo "Langkah selanjutnya:"
echo "1. Edit token di: nano $INSTALL_DIR/.env"
echo "2. Jalankan bot: systemctl start $SERVICE_NAME"
echo "3. Cek log: journalctl -u $SERVICE_NAME -f"
