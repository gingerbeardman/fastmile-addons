#!/bin/sh
# make-ipsec-secret.sh — write ipsec.secret for agvpn's IPsec mode.
# Run on the Mac before copying device/ to the gateway:
#
#   AGVPN_USER=... AGVPN_PASS=... sh device/make-ipsec-secret.sh
#   (or: set -a; . ./credentials.local; set +a; sh device/make-ipsec-secret.sh)
#
# The values are the IPsec username and password from the AdGuard VPN
# dashboard (router/IPsec credentials). install-agvpn.sh copies the file to
# /data/adguardvpn-cli/ipsec.secret (mode 600) and deletes the upload.
# The file is sourced by agvpn, so the values are single-quoted here.

set -eu
OUT=${1:-$(dirname "$0")/ipsec.secret}
: "${AGVPN_USER:?set AGVPN_USER}"
: "${AGVPN_PASS:?set AGVPN_PASS}"

q() { printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"; }

umask 077
rm -f "$OUT"
{
  printf 'USER=%s\n' "$(q "$AGVPN_USER")"
  printf 'PASS=%s\n' "$(q "$AGVPN_PASS")"
} > "$OUT"
chmod 600 "$OUT"
echo "wrote $OUT (mode 600)"
