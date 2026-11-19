#!/bin/sh
# install.sh — deploy the custom web UI (menu, theme, auto-login, DDNS page)
# onto the gateway. Run ON THE DEVICE as root, from the copied device/ folder.
# Paths on the tested unit:
#   UI   /webs/web_whw/     (docroot /webs, base href /web_whw/)
#   CGI  /webs/*.cgi       (fm-auth.js calls /ddns_uci_web_app.cgi)
# / is an overlay on tmpfs, so the copies below also go into
# /data/sysupgrade.tgz.real. /etc/init.d/1restore extracts
# /data/sysupgrade.tgz onto / at boot and deletes it. The rc.local
# shipped in that archive copies the keeper back once the boot has finished
# (see keeper-pack.sh, which every installer uses to build the archive).
#
# The router's own index.html is patched in place by patch-index.sh (a copy
# of the stock file is kept as index.html.orig). No Nokia file is shipped.
#
# NOTE: this script builds the boot archive FROM SCRATCH. Run it first, then
# install-adblock.sh / install-speedtest.sh / install-agvpn.sh, which add to it.

set -e
WEBROOT=/webs/web_whw
CGI=/webs/ddns_uci_web_app.cgi
DIR=$(dirname "$0")
SRC=$DIR/www
STAMP=$(date +%Y%m%d-%H%M%S)

echo "== backing up stock files to /data/ddns-ui-backup-$STAMP =="
mkdir -p /data/ddns-ui-backup-$STAMP
cp -a "$WEBROOT/index.html" /data/ddns-ui-backup-$STAMP/index.html.orig
cp -a /etc/rc.local /data/ddns-ui-backup-$STAMP/rc.local.orig
[ -f /etc/config/ddns ] && cp -a /etc/config/ddns /data/ddns-ui-backup-$STAMP/ddns.orig

echo "== installing custom web files =="
cp "$SRC/fm-auth.js"  "$WEBROOT/fm-auth.js"
cp "$SRC/fm-menu.js"  "$WEBROOT/fm-menu.js"
cp "$SRC/fm-sysinfo.js" "$WEBROOT/fm-sysinfo.js"
cp "$SRC/fm-theme.js"  "$WEBROOT/fm-theme.js"
cp "$SRC/fm-theme.css" "$WEBROOT/fm-theme.css"
cp "$SRC/ddns.html"   "$WEBROOT/ddns.html"
[ -f "$SRC/adblock.html" ] && cp "$SRC/adblock.html" "$WEBROOT/adblock.html"
[ -f "$SRC/vpn.html" ] && cp "$SRC/vpn.html" "$WEBROOT/vpn.html"
sh "$DIR/patch-index.sh" "$WEBROOT/index.html"
cp "$DIR/cgi/ddns_uci_web_app.cgi" "$CGI"
cp "$DIR/cgi/sysinfo_web_app.cgi" /webs/sysinfo_web_app.cgi
if [ -f "$DIR/cgi/adblock_web_app.cgi" ]; then
  cp "$DIR/cgi/adblock_web_app.cgi" /webs/adblock_web_app.cgi
  chmod 755 /webs/adblock_web_app.cgi
fi
chmod 755 "$WEBROOT/fm-auth.js" "$WEBROOT/fm-menu.js" "$WEBROOT/fm-sysinfo.js" "$WEBROOT/ddns.html" \
  "$WEBROOT/index.html" "$CGI" /webs/sysinfo_web_app.cgi
[ -f "$WEBROOT/adblock.html" ] && chmod 755 "$WEBROOT/adblock.html"
[ -f "$WEBROOT/vpn.html" ] && chmod 755 "$WEBROOT/vpn.html"

# The archive re-arm block is written into the archive's copy of rc.local by
# keeper-pack.sh (fail-safe: only after pcd has started), not here.
echo "== rc.local DDNS hook =="
if ! grep -q '/data/config/ddns' /etc/rc.local; then
  awk '
    /^exit 0$/ && !done {
      print "# DDNS uci lives on the overlay. The keeper is /data/config/ddns."
      print "if [ -f /data/config/ddns ]; then"
      print "  cp /data/config/ddns /etc/config/ddns"
      print "  if [ \"$(uci -q get ddns.myddns.enabled)\" = \"1\" ]; then"
      print "    /etc/init.d/ddns restart"
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
STAGE=/tmp/fm-ddns-stage
rm -rf "$STAGE"
mkdir -p "$STAGE/webs/web_whw" "$STAGE/etc"
cp "$WEBROOT/fm-auth.js" "$WEBROOT/fm-menu.js" "$WEBROOT/fm-sysinfo.js" "$WEBROOT/fm-theme.js" \
  "$WEBROOT/fm-theme.css" "$WEBROOT/ddns.html" "$WEBROOT/index.html" \
  "$WEBROOT/index.html.orig" "$STAGE/webs/web_whw/"
mkdir -p "$STAGE/webs/web_whw/assets/i18n"
cp "$WEBROOT/assets/i18n/en.json" "$WEBROOT/assets/i18n/ja.json" \
  "$STAGE/webs/web_whw/assets/i18n/"
cp "$CGI" "$STAGE/webs/ddns_uci_web_app.cgi"
cp /webs/sysinfo_web_app.cgi "$STAGE/webs/sysinfo_web_app.cgi"
if [ -f /webs/adblock_web_app.cgi ]; then
  cp /webs/adblock_web_app.cgi "$STAGE/webs/adblock_web_app.cgi"
fi
if [ -f "$WEBROOT/adblock.html" ]; then
  cp "$WEBROOT/adblock.html" "$STAGE/webs/web_whw/adblock.html"
fi
if [ -f "$WEBROOT/vpn.html" ]; then
  cp "$WEBROOT/vpn.html" "$STAGE/webs/web_whw/vpn.html"
fi
if [ -f /webs/speed_test_status_web_app.cgi ]; then
  cp /webs/speed_test_status_web_app.cgi "$STAGE/webs/speed_test_status_web_app.cgi"
fi
for b in "$WEBROOT"/main.*.js; do
  [ -f "$b" ] || continue
  if grep -F -q 'API_ENDPOINT+"speed_test_status_web_app.cgi"' "$b"; then
    cp "$b" "$STAGE/webs/web_whw/$(basename "$b")"
  fi
done
cp /etc/rc.local "$STAGE/etc/rc.local"
if [ -x /usr/bin/adblock.sh ]; then
  mkdir -p "$STAGE/usr/bin" "$STAGE/usr/libexec" "$STAGE/etc/init.d" \
    "$STAGE/etc/adblock" "$STAGE/etc/config"
  cp /usr/bin/adblock.sh "$STAGE/usr/bin/adblock.sh"
  cp /etc/init.d/adblock "$STAGE/etc/init.d/adblock"
  cp /etc/config/adblock "$STAGE/etc/config/adblock"
  cp /etc/adblock/adblock.sources.gz /etc/adblock/adblock.blacklist \
    /etc/adblock/adblock.whitelist /etc/adblock/adblock.categories \
    /etc/adblock/adblock.mail "$STAGE/etc/adblock/"
  [ -x /usr/libexec/sort-coreutils ] && cp /usr/libexec/sort-coreutils "$STAGE/usr/libexec/sort-coreutils"
  [ -x /usr/bin/sort ] && cp /usr/bin/sort "$STAGE/usr/bin/sort"
fi
sh "$(dirname "$0")/keeper-pack.sh" "$STAGE" /data/sysupgrade.tgz.real || exit 1
cp /data/sysupgrade.tgz.real /data/sysupgrade.tgz
rm -rf "$STAGE"
echo "  archive members:"
tar tzf /data/sysupgrade.tgz.real

echo "== sanity =="
[ -x /usr/lib/ddns/dynamic_dns_updater.sh ] && echo "  ddns-scripts OK" \
  || echo "  WARNING: ddns-scripts not found"
[ -x "$CGI" ] && echo "  cgi OK"

cat <<EOF

Installed.
  DDNS page:  http://192.168.1.1/web_whw/ddns.html
  CGI:        http://192.168.1.1/ddns_uci_web_app.cgi
  Keeper:     /data/sysupgrade.tgz.real
  Next boot:  1restore applies /data/sysupgrade.tgz; rc.local re-arms it once pcd has started.

Revert this boot: cp $WEBROOT/index.html.orig $WEBROOT/index.html
  and rm $WEBROOT/ddns.html $WEBROOT/fm-auth.js $WEBROOT/fm-menu.js $WEBROOT/fm-sysinfo.js
  $CGI /webs/sysinfo_web_app.cgi
  A reboot still reapplies the archive until /data/sysupgrade.tgz and
  /data/sysupgrade.tgz.real are removed.
EOF
