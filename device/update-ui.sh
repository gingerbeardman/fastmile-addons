#!/bin/sh
# update-ui.sh — push changed UI files (menu, theme, pages) to the gateway.
# Run ON THE DEVICE as root, from a directory holding this script,
# patch-index.sh and www/.
#
# Only the web files below are replaced, live and in the boot keeper
# (/data/sysupgrade.tgz.real). Every other keeper member (CGIs, adblock,
# rc.local, patched main.*.js) is kept as it is.
#
# Afterwards it prints the speed test run state (read-only) for debugging.

set -e
WEBROOT=/webs/web_whw
SRC=$(dirname "$0")/www
STAMP=$(date +%Y%m%d-%H%M%S)
DIR=$(dirname "$0")
FILES="fm-menu.js fm-auth.js fm-theme.css fm-theme.js ddns.html adblock.html vpn.html"

[ -f /data/sysupgrade.tgz.real ] || {
  echo "/data/sysupgrade.tgz.real missing; refusing to build a new archive" >&2
  exit 1
}
for f in $FILES; do
  [ -f "$SRC/$f" ] || { echo "missing $SRC/$f" >&2; exit 1; }
done
[ -f "$DIR/patch-index.sh" ] || { echo "missing $DIR/patch-index.sh" >&2; exit 1; }

echo "== backup to /data/ui-backup-$STAMP =="
mkdir -p "/data/ui-backup-$STAMP"
for f in $FILES index.html; do
  [ -f "$WEBROOT/$f" ] && cp -a "$WEBROOT/$f" "/data/ui-backup-$STAMP/$f"
done
cp -a /data/sysupgrade.tgz.real "/data/ui-backup-$STAMP/sysupgrade.tgz.real"

echo "== live files =="
for f in $FILES; do
  cp "$SRC/$f" "$WEBROOT/$f"
  chmod 755 "$WEBROOT/$f"
  echo "  $f"
done
# Regenerates index.html from index.html.orig with the current ?v= numbers.
sh "$DIR/patch-index.sh" "$WEBROOT/index.html"

echo "== boot archive (keeps the other keeper members) =="
STAGE=/tmp/fm-ui-stage
rm -rf "$STAGE"
mkdir -p "$STAGE"
tar xzf /data/sysupgrade.tgz.real -C "$STAGE"
mkdir -p "$STAGE/webs/web_whw"
for f in $FILES index.html index.html.orig; do
  cp "$WEBROOT/$f" "$STAGE/webs/web_whw/$f"
done
tar czf /tmp/fm-ui-keeper.tgz -C "$STAGE" .
tar tzf /tmp/fm-ui-keeper.tgz >/dev/null
mv /tmp/fm-ui-keeper.tgz /data/sysupgrade.tgz.real
cp /data/sysupgrade.tgz.real /data/sysupgrade.tgz
rm -rf "$STAGE"
echo "  archive members:"
tar tzf /data/sysupgrade.tgz.real

cat <<EOF

Updated. Reload http://192.168.1.1/web_whw/ (versioned URLs bypass the cache).
Revert: cp /data/ui-backup-$STAMP/* back into $WEBROOT, and
  cp /data/ui-backup-$STAMP/sysupgrade.tgz.real /data/sysupgrade.tgz.real

EOF

echo "== speed test state (read-only) =="
cd /tmp/speedtest 2>/dev/null || { echo "  no /tmp/speedtest (no run since boot)"; exit 0; }
for f in status rc worker.err down.err up.err dl.samples ookla.json latest.json; do
  echo "-- $f"
  tail -n 15 "$f" 2>/dev/null || true
done
echo "-- curl"
curl --version 2>&1 | head -n 1
