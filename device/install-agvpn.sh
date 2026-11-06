#!/bin/sh
# install-agvpn.sh — install the AdGuard VPN supervisor. Run ON THE DEVICE as root.
#
# Expects /data/adguardvpn-cli/adguardvpn-cli (the static aarch64 CLI, from
# pkg/adguardvpn-cli after running fetch-packages.sh on the Mac) and a
# logged-in CLI data dir at /data/adguardvpn-cli/data (see docs/vpn.md).
# Copies agvpn and agvpn.init from agvpn/ next to this script.
#
# Optional, for IPsec mode:
#   pkg/strongswan/      strongSwan, unpacked by fetch-packages.sh
#   agvpn/ipsec-servers  your server list; copy agvpn/ipsec-servers.example and
#                        fill in the hostnames from the AdGuard dashboard
#   ipsec.secret         USER=/PASS= for AdGuard's IPsec servers, created by
#                        you (make-ipsec-secret.sh). Removed after it is copied.
#
# Creates /data/adguardvpn-cli/agvpn.conf if missing (disabled, no devices;
# pick them on the VPN page or with: agvpn set devices "<ips>").
# Adds an rc.local hook and puts the scripts in the boot archive. The binary,
# login and settings stay in /data, not in the archive.

set -e
SRC=$(dirname "$0")
B=/data/adguardvpn-cli

[ -f "$SRC/agvpn/agvpn" ] && [ -f "$SRC/agvpn/agvpn.init" ] || { echo "missing agvpn/ files" >&2; exit 1; }
if [ -f "$SRC/pkg/adguardvpn-cli" ] && ! cmp -s "$SRC/pkg/adguardvpn-cli" "$B/adguardvpn-cli" 2>/dev/null; then
	mkdir -p "$B"; cp "$SRC/pkg/adguardvpn-cli" "$B/adguardvpn-cli"
	echo "copied pkg/adguardvpn-cli to $B"
fi
[ -x "$B/adguardvpn-cli" ] || [ -f "$B/adguardvpn-cli" ] || { echo "missing $B/adguardvpn-cli" >&2; exit 1; }
[ -d "$B/data" ] || { echo "missing $B/data (log in first)" >&2; exit 1; }
[ -f /data/sysupgrade.tgz.real ] || { echo "missing /data/sysupgrade.tgz.real" >&2; exit 1; }

STAMP=$(date +%Y%m%d-%H%M%S)
BK=/data/agvpn-backup-$STAMP
mkdir -p "$BK"
cp /etc/rc.local "$BK/" ; cp /data/sysupgrade.tgz.real "$BK/"
[ -f /usr/sbin/agvpn ] && cp /usr/sbin/agvpn "$BK/"
echo "backup: $BK"

echo "== files =="
cp "$SRC/agvpn/agvpn" /usr/sbin/agvpn
cp "$SRC/agvpn/agvpn.init" /etc/init.d/agvpn
chmod 755 /usr/sbin/agvpn /etc/init.d/agvpn
if [ ! -f "$B/agvpn.conf" ]; then
	umask 077
	printf 'ENABLED=0\nLOCATION="fastest"\nSCOPE=devices\nDEVICES=""\n' > "$B/agvpn.conf"
fi
chmod 700 "$B" "$B/data"
cat "$B/agvpn.conf"

echo "== cgi =="
cp "$SRC/cgi/agvpn_web_app.cgi" /webs/agvpn_web_app.cgi
chmod 755 /webs/agvpn_web_app.cgi

echo "== strongSwan + ipsec =="
if [ -d "$SRC/pkg/strongswan" ]; then
	(cd "$SRC/pkg/strongswan" && find . -type f -o -type l) > /tmp/agvpn-sw.list
	cp -a "$SRC/pkg/strongswan/." /
	chmod 755 /usr/lib/ipsec/charon /usr/sbin/swanctl
fi
if [ -f "$SRC/agvpn/ipsec-servers" ]; then
	cp "$SRC/agvpn/ipsec-servers" "$B/ipsec-servers"
elif [ ! -f "$B/ipsec-servers" ]; then
	echo "note: no agvpn/ipsec-servers; IPsec mode stays unavailable (CLI mode works)"
fi
if [ -f "$SRC/ipsec.secret" ]; then
	umask 077; cp "$SRC/ipsec.secret" "$B/ipsec.secret"; rm -f "$SRC/ipsec.secret"
fi
chmod 600 "$B/ipsec.secret" 2>/dev/null || true
ls -l "$B"

echo "== rc.local =="
if ! grep -q '/etc/init.d/agvpn' /etc/rc.local; then
	awk '
		/^exit 0$/ && !done {
			print "# AdGuard VPN. Settings and login are in /data/adguardvpn-cli."
			print "[ -x /etc/init.d/agvpn ] && /etc/init.d/agvpn start"
			done=1
		}
		{ print }
	' /etc/rc.local > /tmp/rc.local.new
	cat /tmp/rc.local.new > /etc/rc.local
	rm -f /tmp/rc.local.new
	chmod 755 /etc/rc.local
fi
grep -n agvpn /etc/rc.local

echo "== boot archive =="
STAGE=/tmp/fm-agvpn-stage
rm -rf "$STAGE"; mkdir -p "$STAGE"
tar xzf /data/sysupgrade.tgz.real -C "$STAGE"
mkdir -p "$STAGE/usr/sbin" "$STAGE/etc/init.d"
cp /usr/sbin/agvpn "$STAGE/usr/sbin/agvpn"
cp /etc/init.d/agvpn "$STAGE/etc/init.d/agvpn"
cp /etc/rc.local "$STAGE/etc/rc.local"
mkdir -p "$STAGE/webs"; cp /webs/agvpn_web_app.cgi "$STAGE/webs/agvpn_web_app.cgi"
if [ -f /tmp/agvpn-sw.list ]; then
	while read -r f; do
		mkdir -p "$STAGE/$(dirname "$f")"; cp -a "/$f" "$STAGE/$f"
	done < /tmp/agvpn-sw.list
	rm -f "$STAGE/etc/swanctl/swanctl.conf" /tmp/agvpn-sw.list
fi
tar czf /data/sysupgrade.tgz.real -C "$STAGE" .
cp /data/sysupgrade.tgz.real /data/sysupgrade.tgz
rm -rf "$STAGE"
tar tzf /data/sysupgrade.tgz.real | grep -E 'agvpn|rc.local|charon$|swanctl$' 

echo "installed. enable with: agvpn enable"
