#!/usr/bin/env bash
# =============================================================================
# DBE Credit Intelligence — one-file install (USB / on-prem)
#
# Easy guide for people:  open START_HERE.txt
#
#   cd /path/to/dbe_loan
#   chmod +x INSTALL_ON_SERVER.sh
#   ./INSTALL_ON_SERVER.sh
#
# Needs: Ubuntu 22.04/24.04, Docker (or internet + sudo to install it).
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

RED=$'\033[31m'
GRN=$'\033[32m'
YLW=$'\033[33m'
BLD=$'\033[1m'
RST=$'\033[0m'

say() { echo "${BLD}$*${RST}"; }
ok() { echo "${GRN}✓${RST} $*"; }
warn() { echo "${YLW}!${RST} $*"; }
die() { echo "${RED}✗${RST} $*" >&2; exit 1; }

# --- Step 0: basics ----------------------------------------------------------
say "DBE Credit Intelligence — install"
echo "Folder: $ROOT"
echo

if [[ "$(id -u)" -eq 0 ]]; then
  warn "Running as root is OK, but prefer a normal user in the docker group."
fi

# --- Step 1: install Docker if missing ---------------------------------------
install_docker() {
  say "Docker not found — installing (needs internet + sudo)…"
  need_sudo
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL https://get.docker.com | sudo sh
  else
    sudo apt-get update
    sudo apt-get install -y ca-certificates curl
    curl -fsSL https://get.docker.com | sudo sh
  fi
  if [[ -n "${SUDO_USER:-}" ]]; then
    sudo usermod -aG docker "$SUDO_USER" || true
  elif [[ "$(id -u)" -ne 0 ]]; then
    sudo usermod -aG docker "$USER" || true
  fi
  ok "Docker installed"
  warn "If 'docker' still fails, log out and back in (or reboot), then re-run this script."
}

need_sudo() {
  if [[ "$(id -u)" -eq 0 ]]; then
    return 0
  fi
  command -v sudo >/dev/null 2>&1 || die "sudo required to install Docker"
  sudo -n true 2>/dev/null || sudo -v || die "Could not get sudo"
}

if ! command -v docker >/dev/null 2>&1; then
  install_docker
else
  ok "Docker already installed: $(docker --version)"
fi

docker compose version >/dev/null 2>&1 || die "Docker Compose v2 missing (need: docker compose …)"

# Can we talk to the daemon?
if ! docker info >/dev/null 2>&1; then
  if [[ "$(id -u)" -ne 0 ]] && command -v sudo >/dev/null 2>&1; then
    warn "No permission for Docker socket — retrying with sudo, and adding you to docker group…"
    sudo usermod -aG docker "$USER" || true
    if ! sudo docker info >/dev/null 2>&1; then
      die "Docker daemon not running. Try: sudo systemctl start docker"
    fi
    DOCKER=(sudo docker)
    COMPOSE=(sudo docker compose)
  else
    die "Cannot talk to Docker. Start it: sudo systemctl enable --now docker"
  fi
else
  DOCKER=(docker)
  COMPOSE=(docker compose)
fi

# --- Step 2: host / license / .env -------------------------------------------
detect_host() {
  if [[ -n "${SITE_HOST:-}" ]]; then
    echo "$SITE_HOST"
    return
  fi
  local ip
  ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  [[ -n "$ip" ]] && echo "$ip" && return
  echo "127.0.0.1"
}

gen_secret() {
  if command -v python3 >/dev/null 2>&1; then
    python3 -c 'import secrets; print(secrets.token_urlsafe(50))'
  else
    head -c 48 /dev/urandom | base64 | tr -d '\n+/=' | head -c 64
  fi
}

resolve_license() {
  if [[ -n "${LICENSE_KEY:-}" ]]; then
    echo "$LICENSE_KEY"
    return
  fi
  local f
  for f in \
    "$ROOT/deploy/license/license.key" \
    "$ROOT/docs/deployment/DBE_LICENSE_KEY_1MONTH.txt" \
    "$ROOT/docs/deployment/DEDEbit_LICENSE_KEY_7DAY.txt" \
    "$ROOT/docs/deployment/DEDEbit_LICENSE_KEY_YEAR1.txt"
  do
    if [[ -f "$f" ]]; then
      awk 'NF && $0 !~ /^#/ {print; exit}' "$f"
      return
    fi
  done
  echo ""
}

fill_env_placeholders() {
  sed -i.bak \
    -e "s|REPLACE_WITH_SERVER_IP|${HOST}|g" \
    -e "s|REPLACE_WITH_LONG_RANDOM_SECRET|$(gen_secret)|g" \
    -e "s|REPLACE_WITH_STRONG_DB_PASSWORD|decsiloandbpassword|g" \
    -e "s|REPLACE_WITH_SEQLA1_LICENSE_KEY|${LICENSE}|g" \
    .env
  if grep -q '^ALLOWED_HOSTS=' .env; then
    sed -i "s|^ALLOWED_HOSTS=.*|ALLOWED_HOSTS=localhost,127.0.0.1,${HOST}|" .env
  fi
  if grep -q '^SITE_URL=' .env; then
    sed -i "s|^SITE_URL=.*|SITE_URL=http://${HOST}:${PORT}|" .env
  fi
  if grep -q '^WEB_PORT=' .env; then
    sed -i "s|^WEB_PORT=.*|WEB_PORT=${PORT}|" .env
  else
    echo "WEB_PORT=${PORT}" >> .env
  fi
  if [[ -n "$LICENSE" ]]; then
    if grep -q '^LICENSE_KEY=' .env; then
      sed -i "s|^LICENSE_KEY=.*|LICENSE_KEY=${LICENSE}|" .env
    else
      echo "LICENSE_KEY=${LICENSE}" >> .env
    fi
  fi
  if grep -q '^LICENSE_GRACE_DAYS=' .env; then
    sed -i 's|^LICENSE_GRACE_DAYS=.*|LICENSE_GRACE_DAYS=0|' .env
  else
    echo 'LICENSE_GRACE_DAYS=0' >> .env
  fi
  rm -f .env.bak
}

HOST="$(detect_host)"
PORT="${WEB_PORT:-8000}"
LICENSE="$(resolve_license | tr -d '\r' | head -n1)"

if [[ -z "$LICENSE" ]]; then
  warn "No LICENSE_KEY found."
  warn "Put key in deploy/license/license.key or: export LICENSE_KEY='SEQLA1.…'"
  if [[ "${NONINTERACTIVE:-0}" != "1" ]]; then
    read -r -p "Paste LICENSE_KEY now (or Enter to continue without): " LICENSE || true
  fi
fi

if [[ ! -f .env ]]; then
  say "Creating .env …"
  if [[ -f .env.example ]]; then
    cp .env.example .env
    fill_env_placeholders
    ok "Wrote .env from .env.example (server IP: ${HOST})"
  else
    SECRET="$(gen_secret)"
    cat > .env <<EOF
# Generated by INSTALL_ON_SERVER.sh — $(date -u +%Y-%m-%dT%H:%MZ)
SECRET_KEY=${SECRET}
DEBUG=False
ALLOWED_HOSTS=localhost,127.0.0.1,${HOST}
SITE_URL=http://${HOST}:${PORT}
WEB_PORT=${PORT}

DB_NAME=decsiloandb
DB_USER=decsiloandbuser
DB_PASSWORD=decsiloandbpassword
DB_HOST=db
DB_PORT=5432

LICENSE_KEY=${LICENSE}
LICENSE_ENFORCE=True
LICENSE_GRACE_DAYS=0

LOGIN_MAX_FAILED_ATTEMPTS=5
LOGIN_LOCKOUT_MINUTES=15
MFA_REQUIRED=False
MFA_TOTP_ISSUER=DBE Credit Intelligence
SESSION_IDLE_TIMEOUT=1800

INSTITUTION_NAME=Development Bank of Ethiopia
INSTITUTION_SHORT=DBE
PRODUCT_NAME=Credit Intelligence

DECSI_CUSTOMER_FALLBACK_MOCK=True
DECSI_CBS_USE_MOCK_LEDGER=True
CHAPA_FORCE_MOCK=True
DOCUMENT_OCR_LANG=eng+amh
EOF
    ok "Wrote .env"
  fi
else
  ok ".env already exists — updating placeholders if needed"
  if grep -q 'REPLACE_WITH_SERVER_IP' .env 2>/dev/null; then
    fill_env_placeholders
    ok "Filled server IP in existing .env → ${HOST}"
  fi
  if [[ -n "$LICENSE" ]] && ! grep -qE '^LICENSE_KEY=SEQLA1' .env 2>/dev/null; then
    if grep -qE '^LICENSE_KEY=\s*$|^LICENSE_KEY=REPLACE' .env 2>/dev/null; then
      sed -i.bak "s|^LICENSE_KEY=.*|LICENSE_KEY=${LICENSE}|" .env
      rm -f .env.bak
      ok "Filled LICENSE_KEY in existing .env"
    elif ! grep -q '^LICENSE_KEY=' .env; then
      echo "LICENSE_KEY=${LICENSE}" >> .env
      ok "Appended LICENSE_KEY to .env"
    fi
  fi
fi

if [[ -n "$LICENSE" ]]; then
  mkdir -p deploy/license
  printf '%s\n' "$LICENSE" > deploy/license/license.key
  ok "Saved deploy/license/license.key"
fi

# --- Step 3: start stack -----------------------------------------------------
say "Building and starting containers (first run can take several minutes)…"
"${COMPOSE[@]}" up --build -d

say "Waiting for database…"
for i in $(seq 1 60); do
  if "${COMPOSE[@]}" exec -T db pg_isready -U "${DB_USER:-decsiloandbuser}" -d "${DB_NAME:-decsiloandb}" >/dev/null 2>&1; then
    ok "Database ready"
    break
  fi
  if [[ "$i" -eq 60 ]]; then
    die "Database not ready — run: ${COMPOSE[*]} logs db"
  fi
  sleep 2
done

say "Running migrations…"
"${COMPOSE[@]}" exec -T web python manage.py migrate --noinput
ok "Migrations done"

say "License check…"
"${COMPOSE[@]}" exec -T -e LICENSE_ENFORCE=True web python manage.py check_license \
  || warn "License issue — open http://${HOST}:${PORT}/license/"

CREATE="${CREATE_SUPERUSER:-}"
if [[ -z "$CREATE" && "${NONINTERACTIVE:-0}" != "1" ]]; then
  read -r -p "Create admin (superuser) now? [Y/n] " ans || true
  ans="${ans:-Y}"
  [[ "$ans" =~ ^[Yy]$ ]] && CREATE=1
fi
if [[ "${CREATE:-0}" == "1" ]]; then
  "${COMPOSE[@]}" exec -it web python manage.py createsuperuser \
    || warn "Superuser step skipped or failed"
fi

echo
say "DONE — DBE Credit Intelligence is running"
echo
echo "  Staff hub:      http://${HOST}:${PORT}/hub/login/"
echo "  Digital Apply:  http://${HOST}:${PORT}/"
echo "  License:        http://${HOST}:${PORT}/license/"
echo
echo "Useful:"
echo "  ${COMPOSE[*]} ps"
echo "  ${COMPOSE[*]} logs -f web"
echo "  ${COMPOSE[*]} restart web"
echo "  ${COMPOSE[*]} down"
echo
