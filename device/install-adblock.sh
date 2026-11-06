#!/bin/sh
# install-adblock.sh — install OpenWrt adblock 4.1 and the Security page.
# Run ON THE DEVICE as root.
#
# The Nokia feed is not on downloads.openwrt.org. adblock 4.1.3-9 is an
# architecture-independent package. It refuses to run without GNU sort, so
# coreutils-sort 8.32-6 from OpenWrt 21.02.2 (aarch64_cortex-a53) is installed
# beside it. That binary links only against musl and libgcc and runs on this
# Cortex-A55. Both are copied from pkg/ next to this script, which
# fetch-packages.sh fills on the Mac (pkg/adblock/ and pkg/sort-coreutils).
#
# The service is left disabled. The page turns it on. Blocklists are fetched
# to /tmp on each start, so they are not stored in the boot archive.

set -e
WEBROOT=/webs/web_whw
CGI=/webs/adblock_web_app.cgi
SRC=$(dirname "$0")
PKG=$SRC/pkg/adblock

[ -x "$PKG/usr/bin/adblock.sh" ] || { echo "missing $PKG (run fetch-packages.sh on the Mac first)" >&2; exit 1; }
[ -x "$SRC/pkg/sort-coreutils" ] || { echo "missing pkg/sort-coreutils (run fetch-packages.sh on the Mac first)" >&2; exit 1; }
[ -f /data/sysupgrade.tgz.real ] || { echo "missing /data/sysupgrade.tgz.real" >&2; exit 1; }

echo "== gnu sort =="
mkdir -p /usr/libexec
if [ ! -f /usr/bin/sort.busybox ]; then
  cp -a /usr/bin/sort /usr/bin/sort.busybox
fi
cp "$SRC/pkg/sort-coreutils" /usr/libexec/sort-coreutils
cp "$SRC/pkg/sort-coreutils" /usr/bin/sort
chmod 755 /usr/libexec/sort-coreutils /usr/bin/sort
sort --version | head -n 1 | grep -q coreutils

echo "== adblock files =="
mkdir -p /usr/bin /etc/init.d /etc/adblock /etc/config
cp "$PKG/usr/bin/adblock.sh" /usr/bin/adblock.sh
cp "$PKG/etc/init.d/adblock" /etc/init.d/adblock
cp "$PKG/etc/adblock/"* /etc/adblock/
# Keep a config the user has already saved.
if [ ! -f /data/config/adblock ]; then
  cp "$PKG/etc/config/adblock" /etc/config/adblock
  mkdir -p /data/config
  cp /etc/config/adblock /data/config/adblock
  chmod 600 /data/config/adblock
else
  cp /data/config/adblock /etc/config/adblock
fi
chmod 755 /usr/bin/adblock.sh /etc/init.d/adblock

echo "== web =="
cp "$SRC/www/fm-menu.js" "$WEBROOT/fm-menu.js"
cp "$SRC/www/fm-theme.js" "$WEBROOT/fm-theme.js"
cp "$SRC/www/fm-theme.css" "$WEBROOT/fm-theme.css"
cp "$SRC/www/adblock.html" "$WEBROOT/adblock.html"
cp "$SRC/cgi/adblock_web_app.cgi" "$CGI"
chmod 755 "$WEBROOT/fm-menu.js" "$WEBROOT/adblock.html" "$CGI"

echo "== rc.local =="
if ! grep -q '/data/config/adblock' /etc/rc.local; then
  awk '
    /^exit 0$/ && !done {
      print "# adblock config is on the overlay. The keeper is /data/config/adblock."
      print "if [ -f /data/config/adblock ]; then"
      print "  cp /data/config/adblock /etc/config/adblock"
      print "  if [ \"$(uci -q get adblock.global.adb_enabled)\" = \"1\" ]; then"
      print "    /etc/init.d/adblock enable"
      print "    /etc/init.d/adblock start"
      print "  fi"
      print "fi"
      done=1
    }
    { print }
  ' /etc/rc.local > /tmp/rc.local.new
  cat /tmp/rc.local.new > /etc/rc.local
  rm -f /tmp/rc.local.new
  chmod 755 /etc/rc.local
fi

echo "== boot archive =="
STAGE=/tmp/fm-adblock-stage
rm -rf "$STAGE"
mkdir -p "$STAGE"
tar xzf /data/sysupgrade.tgz.real -C "$STAGE"
mkdir -p "$STAGE/webs/web_whw" "$STAGE/usr/bin" "$STAGE/usr/libexec" \
  "$STAGE/etc/init.d" "$STAGE/etc/adblock" "$STAGE/etc/config"
cp "$CGI" "$STAGE/webs/adblock_web_app.cgi"
cp "$WEBROOT/adblock.html" "$WEBROOT/fm-menu.js" \
  "$WEBROOT/fm-theme.js" "$WEBROOT/fm-theme.css" "$STAGE/webs/web_whw/"
cp /usr/bin/adblock.sh "$STAGE/usr/bin/adblock.sh"
cp /usr/bin/sort "$STAGE/usr/bin/sort"
cp /usr/libexec/sort-coreutils "$STAGE/usr/libexec/sort-coreutils"
cp /etc/init.d/adblock "$STAGE/etc/init.d/adblock"
cp /etc/config/adblock "$STAGE/etc/config/adblock"
cp /etc/adblock/adblock.sources.gz /etc/adblock/adblock.blacklist \
  /etc/adblock/adblock.whitelist /etc/adblock/adblock.categories \
  /etc/adblock/adblock.mail "$STAGE/etc/adblock/"
cp /etc/rc.local "$STAGE/etc/rc.local"
tar czf /data/sysupgrade.tgz.real -C "$STAGE" .
cp /data/sysupgrade.tgz.real /data/sysupgrade.tgz
rm -rf "$STAGE"
echo "  archive members:"
tar tzf /data/sysupgrade.tgz.real

echo "== sanity =="
sort --version | head -n 1
/etc/init.d/adblock version 2>&1 | head -n 2 || true
uci -q get adblock.global.adb_enabled

cat <<EOF

Installed, and left off.
  Page:   http://192.168.1.1/web_whw/adblock.html
  CGI:    http://192.168.1.1/adblock_web_app.cgi
  Keeper: /data/config/adblock and /data/sysupgrade.tgz.real

Save on the page with the switch on to download lists and restart dnsmasq.
EOF
