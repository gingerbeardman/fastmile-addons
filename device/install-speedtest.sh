#!/bin/sh
# install-speedtest.sh — install the Ookla speed test CGI and point the
# Diagnostics page at it. Run ON THE DEVICE as root.
#
# Patches only GetSpeedTestResult() and startSpeedTest() in the live
# main.*.js. Every other call still posts to service_function_web_app.cgi.
# The boot archive is rebuilt from the current keeper, so the DDNS files
# and rc.local reseed stay in it. Run install.sh first.
#
# Browsers cache main.*.js. index.html (patched by patch-index.sh) loads it
# as main.<hash>.js?v=$FM_MAIN_V; bump FM_MAIN_V and re-run update-ui.sh if
# a browser keeps the old bundle.

set -e
WEBROOT=/webs/web_whw
CGI=/webs/speed_test_status_web_app.cgi
SRC=$(dirname "$0")
STAMP=$(date +%Y%m%d-%H%M%S)

OLD_GET='GetSpeedTestResult(){return this.http.post(this.API_ENDPOINT+this.PATH,this.body,this.utils.httpOptionsJson)}'
NEW_GET='GetSpeedTestResult(){return this.http.post(this.API_ENDPOINT+"speed_test_status_web_app.cgi",this.body,this.utils.httpOptionsJson)}'
OLD_START='startSpeedTest(){return this.http.post(this.API_ENDPOINT+this.PATH,this.body,this.utils.httpOptionsJson)}'
NEW_START='startSpeedTest(){return this.http.post(this.API_ENDPOINT+"speed_test_status_web_app.cgi",this.body,this.utils.httpOptionsJson)}'

BUNDLE=$(ls "$WEBROOT"/main.*.js 2>/dev/null | head -n 1)
[ -n "$BUNDLE" ] || { echo "no main.*.js under $WEBROOT" >&2; exit 1; }
[ -f "$SRC/cgi/speed_test_status_web_app.cgi" ] || {
  echo "missing $SRC/cgi/speed_test_status_web_app.cgi" >&2
  exit 1
}

echo "== ookla =="
[ -x /usr/bin/ookla ] || { echo "/usr/bin/ookla missing" >&2; exit 1; }
/usr/bin/ookla --version 2>&1 | head -n 2 || true

echo "== backup =="
mkdir -p "/data/speedtest-ui-backup-$STAMP"
cp -a "$BUNDLE" "/data/speedtest-ui-backup-$STAMP/$(basename "$BUNDLE").orig"
[ -f "$CGI" ] && cp -a "$CGI" "/data/speedtest-ui-backup-$STAMP/speed_test_status_web_app.cgi.orig" || true

echo "== cgi =="
cp "$SRC/cgi/speed_test_status_web_app.cgi" "$CGI"
chmod 755 "$CGI"

echo "== patch bundle =="
if grep -F -q "$NEW_GET" "$BUNDLE" && grep -F -q "$NEW_START" "$BUNDLE"; then
  # (the stock bundle already names speed_test_status_web_app.cgi?start etc.,
  # so only the patched method bodies prove the patch is in)
  echo "  already patched"
else
  tmp=/tmp/main.speedtest.js
  awk -v old1="$OLD_GET" -v new1="$NEW_GET" -v old2="$OLD_START" -v new2="$NEW_START" '
    BEGIN { c1 = 0; c2 = 0 }
    {
      line = $0
      while (i = index(line, old1)) {
        line = substr(line, 1, i - 1) new1 substr(line, i + length(old1))
        c1++
      }
      while (i = index(line, old2)) {
        line = substr(line, 1, i - 1) new2 substr(line, i + length(old2))
        c2++
      }
      print line
    }
    END {
      if (c1 != 1 || c2 != 1) {
        printf "patch count get=%d start=%d (want 1 and 1)\n", c1, c2 > "/dev/stderr"
        exit 1
      }
    }
  ' "$BUNDLE" > "$tmp"
  cat "$tmp" > "$BUNDLE"
  rm -f "$tmp"
fi

grep -F -q "$NEW_GET" "$BUNDLE"
grep -F -q "$NEW_START" "$BUNDLE"
if grep -F -q "$OLD_GET" "$BUNDLE" || grep -F -q "$OLD_START" "$BUNDLE"; then
  echo "old speed test posts are still in the bundle" >&2
  exit 1
fi

echo "== boot archive (keeps the current keeper members) =="
if [ ! -f /data/sysupgrade.tgz.real ]; then
  echo "/data/sysupgrade.tgz.real missing; refusing to build a new archive" >&2
  exit 1
fi
STAGE=/tmp/fm-speed-stage
rm -rf "$STAGE"
mkdir -p "$STAGE"
tar xzf /data/sysupgrade.tgz.real -C "$STAGE"
mkdir -p "$STAGE/webs/web_whw"
cp "$CGI" "$STAGE/webs/speed_test_status_web_app.cgi"
cp "$BUNDLE" "$STAGE/webs/web_whw/$(basename "$BUNDLE")"
tar czf /data/sysupgrade.tgz.real -C "$STAGE" .
cp /data/sysupgrade.tgz.real /data/sysupgrade.tgz
rm -rf "$STAGE"
echo "  archive members:"
tar tzf /data/sysupgrade.tgz.real

echo "== sanity =="
sh "$CGI" --selftest
[ -x "$CGI" ] && echo "  cgi OK"

cat <<EOF

Installed.
  Page:    http://192.168.1.1/web_whw/  Diagnostics, Speed Test
  CGI:     http://192.168.1.1/speed_test_status_web_app.cgi
  Keeper:  /data/sysupgrade.tgz.real
  Backup:  /data/speedtest-ui-backup-$STAMP/

A click measures the default-route interface (download, upload, ping).
Ookla's own client cannot start: its embed configuration URL returns 403.
The run can move up to about 100 MB down and 20 MB up.
Revert this boot:
  cp /data/speedtest-ui-backup-$STAMP/$(basename "$BUNDLE").orig $BUNDLE
  rm -f $CGI
A reboot reapplies the archive until that bundle and CGI are removed from
/data/sysupgrade.tgz and /data/sysupgrade.tgz.real.
EOF
