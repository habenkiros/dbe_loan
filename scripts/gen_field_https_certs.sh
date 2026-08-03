#!/usr/bin/env bash
# Local field HTTPS: root CA + server cert signed by that CA.
#
# Android Chrome will NOT register a service worker for a plain self-signed leaf
# (CA:FALSE). Desktop Chrome often still works after "Proceed anyway".
# Phones need the CA installed as a trusted credential, then the leaf validates.
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

CA_KEY="${CERT_DIR}/decsi-field-ca.key"
CA_CRT="${CERT_DIR}/decsi-field-ca.crt"
SERVER_KEY="${CERT_DIR}/field.key"
SERVER_CRT="${CERT_DIR}/field.crt"
SERVER_CSR="${CERT_DIR}/field.csr"
SERVER_EXT="${CERT_DIR}/server_ext.cnf"
CA_CONF="${CERT_DIR}/ca_openssl.cnf"

# --- Root CA (must be CA:TRUE so Android will install it) ---
cat > "${CA_CONF}" <<EOF
[req]
default_bits = 2048
prompt = no
default_md = sha256
distinguished_name = dn
x509_extensions = v3_ca

[dn]
CN = DECSI Field Local CA
O = DECSI Field Local
C = ET

[v3_ca]
basicConstraints = critical, CA:TRUE
keyUsage = critical, keyCertSign, cRLSign
subjectKeyIdentifier = hash
EOF

openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout "${CA_KEY}" \
  -out "${CA_CRT}" \
  -config "${CA_CONF}"

# --- Server leaf signed by CA ---
cat > "${SERVER_EXT}" <<EOF
[req]
default_bits = 2048
prompt = no
default_md = sha256
distinguished_name = dn
req_extensions = v3_req

[dn]
CN = decsi-field-local
O = DECSI Field Local
C = ET

[v3_req]
basicConstraints = CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names
subjectKeyIdentifier = hash

[alt_names]
DNS.1 = localhost
DNS.2 = *.local
IP.1 = 127.0.0.1
IP.2 = ${LAN_IP}
EOF

openssl req -new -nodes -newkey rsa:2048 \
  -keyout "${SERVER_KEY}" \
  -out "${SERVER_CSR}" \
  -config "${SERVER_EXT}"

openssl x509 -req -in "${SERVER_CSR}" \
  -CA "${CA_CRT}" -CAkey "${CA_KEY}" -CAcreateserial \
  -out "${SERVER_CRT}" -days 825 -sha256 \
  -extfile "${SERVER_EXT}" -extensions v3_req

# Full chain (leaf + CA) — some clients prefer it; nginx can use leaf alone if CA is on the phone.
cat "${SERVER_CRT}" "${CA_CRT}" > "${CERT_DIR}/field-fullchain.crt"

# Copy CA into static so phones can download it over HTTP/HTTPS while on Wi‑Fi.
STATIC_CA_DIR="${ROOT}/static/certs"
mkdir -p "${STATIC_CA_DIR}"
cp "${CA_CRT}" "${STATIC_CA_DIR}/decsi-field-ca.crt"

chmod 600 "${CA_KEY}" "${SERVER_KEY}"
rm -f "${SERVER_CSR}"

ENV_FILE="${ROOT}/deploy/https/.env.https"
cat > "${ENV_FILE}" <<EOF
USE_HTTPS_PROXY=1
HTTPS_SECURE_COOKIES=0
CSRF_TRUSTED_ORIGINS=https://localhost:8443,https://127.0.0.1:8443,https://${LAN_IP}:8443
SITE_URL=https://${LAN_IP}:8443
EOF

echo ""
echo "Wrote CA:     ${CA_CRT}"
echo "Wrote server: ${SERVER_CRT} + ${SERVER_KEY}"
echo "Wrote static: ${STATIC_CA_DIR}/decsi-field-ca.crt"
echo "Wrote env:    ${ENV_FILE} (LAN ${LAN_IP})"
echo ""
echo "PHONE SETUP (required for offline on Android/iOS Chrome/Safari):"
echo "  1. On PC Wi‑Fi open https://${LAN_IP}:8443/collateral/offline/setup/"
echo "  2. Download / install DECSI Field Local CA as a CA certificate"
echo "  3. Reopen https://${LAN_IP}:8443 — address bar must show a lock (no warning)"
echo "  4. Login → field visit → Download for offline → Install app"
echo "  5. Airplane Mode → open Home Screen app only"
echo ""
echo "Start HTTPS with:"
echo "  docker compose -f docker-compose.yml -f docker-compose.https.yml up -d"
echo "Then nginx reload if already running so it picks up the new cert."
