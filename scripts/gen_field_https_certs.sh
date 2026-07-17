#!/usr/bin/env bash
# Generate a self-signed cert for local / LAN tablet HTTPS (field GPS + camera).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CERT_DIR="${ROOT}/deploy/https/certs"
mkdir -p "${CERT_DIR}"

LAN_IP="${1:-}"
if [[ -z "${LAN_IP}" ]]; then
  LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
fi
if [[ -z "${LAN_IP}" ]]; then
  LAN_IP="127.0.0.1"
fi

CONF="${CERT_DIR}/openssl.cnf"
cat > "${CONF}" <<EOF
[req]
default_bits = 2048
prompt = no
default_md = sha256
distinguished_name = dn
x509_extensions = v3_req

[dn]
CN = decsi-field-local
O = DECSI Field Local
C = ET

[v3_req]
subjectAltName = @alt_names
basicConstraints = CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth

[alt_names]
DNS.1 = localhost
DNS.2 = *.local
IP.1 = 127.0.0.1
IP.2 = ${LAN_IP}
EOF

openssl req -x509 -nodes -days 825 -newkey rsa:2048 \
  -keyout "${CERT_DIR}/field.key" \
  -out "${CERT_DIR}/field.crt" \
  -config "${CONF}"

chmod 600 "${CERT_DIR}/field.key"

ENV_FILE="${ROOT}/deploy/https/.env.https"
cat > "${ENV_FILE}" <<EOF
USE_HTTPS_PROXY=1
CSRF_TRUSTED_ORIGINS=https://localhost:8443,https://127.0.0.1:8443,https://${LAN_IP}:8443
SITE_URL=https://${LAN_IP}:8443
EOF

echo "Wrote ${CERT_DIR}/field.crt and field.key"
echo "Wrote ${ENV_FILE} (CSRF trusted origins include ${LAN_IP})"
echo "Start HTTPS with:"
echo "  docker compose -f docker-compose.yml -f docker-compose.https.yml up --build"
echo "Then open https://localhost:8443 or https://${LAN_IP}:8443 on the tablet"
echo "(Accept the browser warning for the self-signed certificate once.)"
