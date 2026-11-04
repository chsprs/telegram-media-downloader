#!/usr/bin/env bash
#
# Telegram Media Downloader — installer untuk Debian / Armbian (HG680P & sejenisnya)
#
# Pakai interaktif:      sudo ./install.sh
# Pakai non-interaktif:  sudo BOT_TOKEN="123:ABC..." ALLOWED_USER_IDS="123456" ./install.sh
#
set -e

INSTALL_DIR="/opt/telegram-media-downloader"
SERVICE_NAME="telegram-downloader.service"
ENV_FILE="$INSTALL_DIR/.env"

TOKEN_BODY='[0-9]{5,}:[A-Za-z0-9_-]{20,}'
TOKEN_RE="^${TOKEN_BODY}\$"

log() { echo "==> $*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "jalankan sebagai root: sudo ./install.sh"

# ---------------------------------------------------------------- 1. dependensi
log "1/6 Memeriksa & menginstall dependensi sistem (python3, venv, ffmpeg)..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 python3-venv ffmpeg curl >/dev/null

# ---------------------------------------------------------------- 2. file app
log "2/6 Menyiapkan direktori aplikasi di $INSTALL_DIR..."
mkdir -p "$INSTALL_DIR"
cp -ru ./* "$INSTALL_DIR/" 2>/dev/null || cp -r ./* "$INSTALL_DIR/"
cd "$INSTALL_DIR"

# ---------------------------------------------------------------- 3. venv
log "3/6 Menyiapkan Python virtual environment..."
[ -d venv ] || python3 -m venv venv
./venv/bin/pip install -q --upgrade pip
./venv/bin/pip install -q -r requirements.txt

# ---------------------------------------------------------------- 4. token
read_token() {
    local t="${BOT_TOKEN:-}"
    local tries=0
    while :; do
        if [ -z "$t" ]; then
            [ -t 0 ] || die "mode non-interaktif: jalankan dengan BOT_TOKEN=... ./install.sh"
            printf '\nMasukkan BOT_TOKEN dari @BotFather (contoh 123456789:AAE...): '
            read -r t
        fi
        t="$(printf '%s' "$t" | tr -d '[:space:]')"
        if [[ "$t" =~ $TOKEN_RE ]]; then
            echo "$t"
            return 0
        fi
        echo "  ! Format token tidak valid. Ambil ulang dari @BotFather (/token)."
        t=""
        tries=$((tries + 1))
        [ "$tries" -lt 5 ] || die "terlalu banyak percobaan token."
    done
}

verify_token() {
    local token="$1" resp
    resp="$(curl -s --max-time 12 "https://api.telegram.org/bot${token}/getMe" || true)"
    case "$resp" in
        *'"ok":true'*)
            echo "$resp" | grep -o '"username":"[^"]*"' | head -1 | cut -d'"' -f4
            return 0
            ;;
        *) return 1 ;;
    esac
}

if [ -f "$ENV_FILE" ] && grep -qE "^BOT_TOKEN=${TOKEN_BODY}\$" "$ENV_FILE" && [ -z "${BOT_TOKEN:-}" ]; then
    log "4/6 .env sudah berisi token valid — dilewati (pakai BOT_TOKEN=... ./install.sh untuk mengganti)."
    BOT_USERNAME=""
else
    log "4/6 Konfigurasi bot token"
    TOKEN="$(read_token)"

    printf 'Memverifikasi token ke Telegram... '
    if BOT_USERNAME="$(verify_token "$TOKEN")"; then
        echo "OK (@${BOT_USERNAME:-unknown})"
    else
        echo "GAGAL"
        die "token ditolak Telegram. Pastikan token benar dan server punya koneksi internet."
    fi

    if [ -n "${ALLOWED_USER_IDS:-}" ]; then
        ALLOWED="$ALLOWED_USER_IDS"
        log "whitelist user: $ALLOWED"
    elif [ -t 0 ]; then
        printf 'Batasi akses ke user ID tertentu? (kosongkan = publik / siapa saja bisa pakai): '
        read -r ALLOWED
        ALLOWED="$(printf '%s' "$ALLOWED" | tr -d '[:space:]')"
    else
        ALLOWED=""
    fi

    umask 077
    cat > "$ENV_FILE" <<EOF
# Dibuat otomatis oleh install.sh — $(date '+%Y-%m-%d %H:%M:%S')
BOT_TOKEN=$TOKEN
ALLOWED_USER_IDS=$ALLOWED
DOWNLOAD_DIR=/tmp/tg_media_downloader
EOF
    chmod 600 "$ENV_FILE"
    log ".env ditulis: $ENV_FILE (permission 600)"
fi

# ---------------------------------------------------------------- 5. systemd
log "5/6 Mendaftarkan systemd service..."
install -m 644 telegram-downloader.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable "$SERVICE_NAME" >/dev/null 2>&1

# ---------------------------------------------------------------- 6. start
log "6/6 Menjalankan bot..."
systemctl restart "$SERVICE_NAME"
sleep 3

if systemctl is-active --quiet "$SERVICE_NAME"; then
    STATE="AKTIF"
else
    STATE="GAGAL"
fi

if [ -z "${BOT_USERNAME:-}" ]; then
    BOT_USERNAME="$(curl -s --max-time 8 "https://api.telegram.org/bot$(grep -oP '(?<=^BOT_TOKEN=).*' "$ENV_FILE")/getMe" \
                   | grep -o '"username":"[^"]*"' | head -1 | cut -d'"' -f4 || true)"
fi

echo ""
echo "=================================================================="
echo " Instalasi selesai — status service: $STATE"
[ -n "${BOT_USERNAME:-}" ] && echo " Buka bot: https://t.me/$BOT_USERNAME  lalu kirim /start"
echo " Log realtime : journalctl -u $SERVICE_NAME -f"
echo " Restart      : systemctl restart $SERVICE_NAME"
echo " Edit config  : nano $ENV_FILE"
echo "=================================================================="
[ "$STATE" = "AKTIF" ] || { journalctl -u "$SERVICE_NAME" -n 20 --no-pager; exit 1; }
