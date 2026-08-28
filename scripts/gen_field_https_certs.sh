#!/usr/bin/env bash
# Local field HTTPS: root CA + server cert signed by that CA.
#
# The server leaf is valid for every current host LAN address, plus the whole
# RFC1918 /24 of each of those addresses. DHCP can change the last octet without
# regenerating. Extra IPs may be passed as arguments (they are added, not required).
#
# Android Chrome will NOT register a service worker for a plain self-signed leaf
# (CA:FALSE). Desktop Chrome often still works after "Proceed anyway".
# Phones need the CA installed as a trusted credential, then the leaf validates.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CERT_DIR="${ROOT}/deploy/https/certs"
mkdir -p "${CERT_DIR}"

is_ipv4() {
  [[ "$1" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || return 1
  local a b c d
  IFS=. read -r a b c d <<< "$1"
  [[ "$a" -le 255 && "$b" -le 255 && "$c" -le 255 && "$d" -le 255 ]]
}

is_skipped_iface() {
  case "$1" in
    lo|lo0|docker*|br-*|veth*|virbr*|cni*|flannel*|tun*|utun*|awdl*|llw*|anpi*|tailscale*|zt*|vnet*)
      return 0
      ;;
  esac
  return 1
}

# RFC1918 only — expanding a public /24 would over-claim names on the field CA.
is_private_ipv4() {
  local a b
  IFS=. read -r a b _ _ <<< "$1"
  [[ "$a" == "10" ]] && return 0
  [[ "$a" == "192" && "$b" == "168" ]] && return 0
  [[ "$a" == "172" && "$b" -ge 16 && "$b" -le 31 ]] && return 0
  return 1
}

collect_host_ipv4s() {
  local iface cidr ip
  if command -v ip >/dev/null 2>&1; then
    while read -r iface cidr; do
      [[ -z "${iface:-}" ]] && continue
      is_skipped_iface "$iface" && continue
      ip="${cidr%%/*}"
      is_ipv4 "$ip" && echo "$ip"
    done < <(ip -4 -o addr show scope global 2>/dev/null | awk '{print $2, $4}')
  fi
  if command -v ifconfig >/dev/null 2>&1; then
    # macOS / BSD (and Linux fallback). Skip tunnel / VM bridges by name when possible.
    while read -r iface ip; do
      [[ -z "${iface:-}" || -z "${ip:-}" ]] && continue
      is_skipped_iface "$iface" && continue
      is_ipv4 "$ip" || continue
      [[ "$ip" == "127.0.0.1" ]] && continue
      echo "$ip"
    done < <(ifconfig 2>/dev/null | awk '
      /^[a-zA-Z0-9]/ { iface=$1; sub(/:$/, "", iface) }
      /inet / { ip=$2; sub(/^addr:/, "", ip); print iface, ip }
    ')
  fi
}

CA_KEY="${CERT_DIR}/decsi-field-ca.key"
CA_CRT="${CERT_DIR}/decsi-field-ca.crt"
SERVER_KEY="${CERT_DIR}/field.key"
SERVER_CRT="${CERT_DIR}/field.crt"
SERVER_CSR="${CERT_DIR}/field.csr"
SERVER_EXT="${CERT_DIR}/server_ext.cnf"
CA_CONF="${CERT_DIR}/ca_openssl.cnf"

# --- Root CA (reuse so phones do not reinstall trust after an IP change) ---
if [[ -f "${CA_KEY}" && -f "${CA_CRT}" ]]; then
  echo "Reusing existing Field CA: ${CA_CRT}"
else
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
fi

HOST_DNS="$(hostname -s 2>/dev/null || hostname | cut -d. -f1 || true)"
HOST_DNS="$(echo "${HOST_DNS}" | tr -cd 'A-Za-z0-9.-')"
[[ -z "${HOST_DNS}" ]] && HOST_DNS="decsi-field"

# Unique IPv4s: loopback + every host LAN address + optional extra args + /24 of each private IP.
# Avoid associative arrays so macOS /bin/bash (3.2) can run this script.
IPS=()
add_ip() {
  local ip="$1" existing
  is_ipv4 "$ip" || return 0
  for existing in "${IPS[@]+"${IPS[@]}"}"; do
    [[ "$existing" == "$ip" ]] && return 0
  done
  IPS+=("$ip")
}

add_ip "127.0.0.1"
while read -r ip; do
  [[ -n "$ip" ]] && add_ip "$ip"
done < <(collect_host_ipv4s | sort -u)

if [[ $# -gt 0 ]]; then
  for extra in "$@"; do
    extra="${extra#https://}"
    extra="${extra#http://}"
    extra="${extra%%:*}"
    extra="${extra%%/*}"
    add_ip "$extra"
  done
fi

# Expand each private address to its /24 so DHCP can move the last octet.
EXPAND=()
for ip in "${IPS[@]}"; do
  if is_private_ipv4 "$ip"; then
    IFS=. read -r a b c _ <<< "$ip"
    EXPAND+=("$a.$b.$c")
  fi
done
if [[ ${#EXPAND[@]} -gt 0 ]]; then
  while read -r net; do
    [[ -z "$net" ]] && continue
    for last in $(seq 1 254); do
      add_ip "${net}.${last}"
    done
  done < <(printf '%s\n' "${EXPAND[@]}" | sort -u)
fi

# --- Server leaf signed by CA ---
{
  cat <<EOF
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
DNS.3 = ${HOST_DNS}
DNS.4 = ${HOST_DNS}.local
DNS.5 = decsi-field.local
EOF
  idx=1
  for ip in "${IPS[@]}"; do
    echo "IP.${idx} = ${ip}"
    idx=$((idx + 1))
  done
} > "${SERVER_EXT}"

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

# Do not pin SITE_URL / CSRF to a single LAN IP — DHCP and extra NICs must work.
# Django ALLOWED_HOSTS is '*' when USE_HTTPS_PROXY=1 (see settings).
ENV_FILE="${ROOT}/deploy/https/.env.https"
cat > "${ENV_FILE}" <<EOF
USE_HTTPS_PROXY=1
HTTPS_SECURE_COOKIES=0
HTTPS_ALLOW_ANY_HOST=1
EOF

SAN_COUNT="${#IPS[@]}"
echo ""
echo "Wrote CA:     ${CA_CRT}"
echo "Wrote server: ${SERVER_CRT} + ${SERVER_KEY}"
echo "Wrote static: ${STATIC_CA_DIR}/decsi-field-ca.crt"
echo "Wrote env:    ${ENV_FILE} (no pinned LAN IP)"
echo "SAN IPs:      ${SAN_COUNT} (localhost + current LAN + each private /24)"
echo ""
echo "PHONE SETUP (required for offline on Android/iOS Chrome/Safari):"
echo "  1. On Wi‑Fi open https://<this-server-ip>:8443/collateral/offline/setup/"
echo "  2. Download / install DECSI Field Local CA as a CA certificate"
echo "  3. Reopen https://<this-server-ip>:8443 — address bar must show a lock (no warning)"
echo "  4. Login → field visit → Download for offline → Install app"
echo "  5. Airplane Mode → open Home Screen app only"
echo ""
echo "Any current (and same-/24 DHCP) address works. After a new subnet, re-run this script"
echo "and reload nginx so the leaf SAN matches."
echo ""
echo "Start HTTPS with:"
echo "  docker compose -f docker-compose.yml -f docker-compose.https.yml up -d"
echo "Then nginx reload if already running so it picks up the new cert."

if command -v docker >/dev/null 2>&1; then
  if docker compose -f "${ROOT}/docker-compose.yml" -f "${ROOT}/docker-compose.https.yml" \
      ps --status running 2>/dev/null | grep -q nginx; then
    docker compose -f "${ROOT}/docker-compose.yml" -f "${ROOT}/docker-compose.https.yml" \
      exec -T nginx nginx -s reload && echo "Reloaded nginx with the new certificate."
  fi
fi
