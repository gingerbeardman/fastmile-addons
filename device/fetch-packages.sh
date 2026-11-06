#!/bin/sh
# fetch-packages.sh — download the third-party packages the installers need
# and unpack them into device/pkg/. Run ON THE MAC (or any Unix box with
# curl, tar, python3 and shasum/sha256sum), before copying device/ to the
# gateway. Nothing here is redistributed by this project.
#
#   sh device/fetch-packages.sh            (re-run any time; pkg/ is rebuilt)
#
# Sources:
#   OpenWrt 21.02.2 aarch64_cortex-a53 "packages" feed
#     (the gateway's own feed name, aarch64_cortex-a55_neon-vfpv4, is not on
#     downloads.openwrt.org; the cortex-a53 builds run on its Cortex-A55)
#     - strongSwan 5.9.2: core, charon, swanctl and the plugins listed below
#     - adblock 4.1.x (architecture independent)
#     - coreutils-sort (GNU sort; adblock refuses BusyBox sort)
#   AdGuard VPN CLI: latest linux-aarch64 release on GitHub
#     (AdguardTeam/AdGuardVPNCLI), checked against the asset's sha256 digest.
#
# Every OpenWrt .ipk is checked against the SHA256sum in the feed index.
#
# Result (the layout the installers expect):
#   pkg/strongswan/      etc/strongswan.conf, etc/strongswan.d/, etc/swanctl/x509ca/,
#                        usr/lib/ipsec/ (charon, libs, plugins), usr/sbin/swanctl
#   pkg/adblock/         usr/bin/adblock.sh, etc/init.d/adblock, etc/config/adblock,
#                        etc/adblock/*
#   pkg/sort-coreutils   the GNU sort binary
#   pkg/adguardvpn-cli   the static AdGuard VPN CLI binary
#
# The CA roots in device/certs/ are copied into pkg/strongswan/etc/swanctl/x509ca/.
# strongswan.conf and the adblock UCI config are replaced with this project's
# versions (written below), not the package defaults.

set -eu

FEED=${FEED:-https://downloads.openwrt.org/releases/21.02.2/packages/aarch64_cortex-a53/packages}
AG_REPO=${AG_REPO:-AdguardTeam/AdGuardVPNCLI}

STRONGSWAN_PKGS="strongswan strongswan-charon strongswan-swanctl
  strongswan-mod-vici strongswan-mod-kernel-netlink strongswan-mod-socket-default
  strongswan-mod-nonce strongswan-mod-openssl strongswan-mod-random
  strongswan-mod-x509 strongswan-mod-pem strongswan-mod-pkcs1 strongswan-mod-pubkey
  strongswan-mod-revocation strongswan-mod-constraints strongswan-mod-eap-mschapv2
  strongswan-mod-eap-identity strongswan-mod-md4 strongswan-mod-des
  strongswan-mod-sha1 strongswan-mod-sha2 strongswan-mod-hmac strongswan-mod-aes
  strongswan-mod-gcm"

DIR=$(cd "$(dirname "$0")" && pwd)
PKG=$DIR/pkg
WORK=$(mktemp -d "${TMPDIR:-/tmp}/fm-fetch.XXXXXX")
trap 'rm -rf "$WORK"' EXIT

for t in curl tar python3; do
  command -v $t >/dev/null 2>&1 || { echo "need $t" >&2; exit 1; }
done
if command -v sha256sum >/dev/null 2>&1; then
  sha256() { sha256sum "$1" | awk '{print $1}'; }
elif command -v shasum >/dev/null 2>&1; then
  sha256() { shasum -a 256 "$1" | awk '{print $1}'; }
else
  echo "need sha256sum or shasum" >&2; exit 1
fi

echo "== feed index =="
curl -fsSL -o "$WORK/Packages" "$FEED/Packages"

# field <package> <Field>: value of Field in the package's stanza
field() {
  awk -v p="$1" -v f="$2" '
    /^Package: / { cur = substr($0, 10) }
    cur == p && index($0, f ": ") == 1 { print substr($0, length(f) + 3); exit }
  ' "$WORK/Packages"
}

# fetch_ipk <package> <destdir>: download, verify and unpack data.tar.gz
fetch_ipk() {
  name=$1; dest=$2
  file=$(field "$name" Filename)
  want=$(field "$name" SHA256sum)
  [ -n "$file" ] && [ -n "$want" ] || { echo "package $name not in feed" >&2; exit 1; }
  curl -fsSL -o "$WORK/$file" "$FEED/$file"
  got=$(sha256 "$WORK/$file")
  [ "$got" = "$want" ] || { echo "sha256 mismatch for $file" >&2; exit 1; }
  x=$WORK/x.$name
  rm -rf "$x"; mkdir -p "$x" "$dest"
  # An .ipk is a gzip'd tar (OpenWrt) or an ar archive (Debian style), both
  # holding data.tar.gz. bsdtar reads both; GNU tar needs ar for the latter.
  if ! tar -xzf "$WORK/$file" -C "$x" 2>/dev/null; then
    if command -v ar >/dev/null 2>&1; then
      (cd "$x" && ar x "$WORK/$file")
    else
      tar -xf "$WORK/$file" -C "$x"
    fi
  fi
  [ -f "$x/data.tar.gz" ] || { echo "no data.tar.gz in $file" >&2; exit 1; }
  tar -xzf "$x/data.tar.gz" -C "$dest"
  echo "  $file"
}

rm -rf "$PKG"
mkdir -p "$PKG"

echo "== strongSwan =="
SW=$WORK/strongswan
for p in $STRONGSWAN_PKGS; do fetch_ipk "$p" "$SW"; done
mkdir -p "$PKG/strongswan/etc/swanctl/x509ca" "$PKG/strongswan/usr/lib" "$PKG/strongswan/usr/sbin"
# Our strongswan.conf: no routes, virtual IP on lo, log to /tmp/charon.log.
cat > "$PKG/strongswan/etc/strongswan.conf" <<'CONF'
# fastmile: AdGuard VPN, IPsec mode (driven by /usr/sbin/agvpn).
# No routes and no interface: agvpn SNATs chosen LAN devices to the virtual IP.
charon {
	load_modular = yes
	install_routes = no
	install_virtual_ip_on = lo
	plugins {
		include strongswan.d/charon/*.conf
	}
	filelog {
		charon {
			path = /tmp/charon.log
			time_format = %b %e %T
			default = 0
			ike = 1
			flush_line = yes
		}
	}
	syslog {
		daemon {
			default = -1
		}
	}
}
CONF
cp -pR "$SW/etc/strongswan.d" "$PKG/strongswan/etc/"
cp -pR "$SW/usr/lib/ipsec" "$PKG/strongswan/usr/lib/"
cp -p "$SW/usr/sbin/swanctl" "$PKG/strongswan/usr/sbin/"
cp "$DIR"/certs/*.pem "$PKG/strongswan/etc/swanctl/x509ca/"
for f in charon libcharon.so.0.0.0 libstrongswan.so.0.0.0 libvici.so.0.0.0; do
  [ -e "$PKG/strongswan/usr/lib/ipsec/$f" ] || { echo "strongSwan: missing usr/lib/ipsec/$f" >&2; exit 1; }
done

echo "== adblock =="
AB=$WORK/adblock
fetch_ipk adblock "$AB"
mkdir -p "$PKG/adblock/usr/bin" "$PKG/adblock/etc/init.d" "$PKG/adblock/etc/config" "$PKG/adblock/etc/adblock"
cp -p "$AB/usr/bin/adblock.sh" "$PKG/adblock/usr/bin/"
cp -p "$AB/etc/init.d/adblock" "$PKG/adblock/etc/init.d/"
# Our default config: off (the Security page turns it on), dnsmasq, curl,
# no backups (lists are fetched to /tmp on each start), four list sources.
cat > "$PKG/adblock/etc/config/adblock" <<'CONF'
config adblock 'global'
	option adb_enabled '0'
	option adb_debug '0'
	option adb_forcedns '0'
	option adb_safesearch '0'
	option adb_dnsfilereset '0'
	option adb_mail '0'
	option adb_report '0'
	option adb_backup '0'
	option adb_dns 'dnsmasq'
	option adb_fetchutil 'curl'
	option adb_maxqueue '4'
	list adb_sources 'adaway'
	list adb_sources 'adguard'
	list adb_sources 'disconnect'
	list adb_sources 'yoyo'
CONF
cp -p "$AB"/etc/adblock/* "$PKG/adblock/etc/adblock/"
# install-adblock.sh and install.sh copy these two lists; create them empty
# if this adblock version doesn't ship them.
for f in adblock.blacklist adblock.whitelist; do
  [ -f "$PKG/adblock/etc/adblock/$f" ] || : > "$PKG/adblock/etc/adblock/$f"
done
chmod 755 "$PKG/adblock/usr/bin/adblock.sh" "$PKG/adblock/etc/init.d/adblock"

echo "== coreutils-sort =="
CS=$WORK/coreutils-sort
fetch_ipk coreutils-sort "$CS"
SORT=
for c in "$CS/usr/libexec/sort-coreutils" "$CS/usr/bin/sort" "$CS/bin/sort"; do
  if [ -f "$c" ] && [ ! -L "$c" ]; then SORT=$c; break; fi
done
[ -n "$SORT" ] || { echo "no sort binary in coreutils-sort" >&2; exit 1; }
cp "$SORT" "$PKG/sort-coreutils"
chmod 755 "$PKG/sort-coreutils"

echo "== AdGuard VPN CLI =="
curl -fsSL -o "$WORK/release.json" "https://api.github.com/repos/$AG_REPO/releases/latest"
python3 -I - "$WORK/release.json" > "$WORK/asset" <<'EOF'
import json, sys
d = json.load(open(sys.argv[1]))
for a in d.get("assets", []):
    n = a.get("name", "")
    if n.endswith("-linux-aarch64.tar.gz"):
        dg = a.get("digest") or ""
        if not dg.startswith("sha256:"):
            sys.exit("asset %s has no sha256 digest" % n)
        print(n, a["browser_download_url"], dg[7:])
        break
else:
    sys.exit("no linux-aarch64 asset in %s" % d.get("tag_name"))
EOF
read -r AG_NAME AG_URL AG_SHA < "$WORK/asset"
curl -fsSL -o "$WORK/$AG_NAME" "$AG_URL"
got=$(sha256 "$WORK/$AG_NAME")
[ "$got" = "$AG_SHA" ] || { echo "sha256 mismatch for $AG_NAME" >&2; exit 1; }
mkdir -p "$WORK/ag"
tar -xzf "$WORK/$AG_NAME" -C "$WORK/ag"
AG_BIN=$(find "$WORK/ag" -type f -name adguardvpn-cli | head -n 1)
[ -n "$AG_BIN" ] || { echo "no adguardvpn-cli in $AG_NAME" >&2; exit 1; }
cp "$AG_BIN" "$PKG/adguardvpn-cli"
chmod 755 "$PKG/adguardvpn-cli"
echo "  $AG_NAME (sha256 OK)"

echo "== done =="
du -sh "$PKG"/* 2>/dev/null
echo "Now copy device/ to the gateway and run the installers as root (see README.md)."
