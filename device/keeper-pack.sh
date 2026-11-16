#!/bin/sh
# keeper-pack.sh — build the boot archive (/data/sysupgrade.tgz.real) safely.
# Run ON THE DEVICE as root. Every installer packs through this script.
#
#   sh keeper-pack.sh STAGE OUT     pack the stage folder into OUT
#   sh keeper-pack.sh --check FILE  exit 1 if FILE is unsafe to restore
#
# Why: /etc/init.d/1restore runs BusyBox `tar -xzf` at / on every boot, and
# BusyBox tar re-applies each DIRECTORY entry's mode and owner to the live
# directory. A stage built under root's umask (027 on this unit) once put
# "./", "etc/" and "usr/" in the archive as 750, so / and /etc became 750 at
# boot, every non-root daemon lost access, pcd never started and the router
# needed a factory reset (2026-11-15). So the archive holds files and
# symlinks only: existing directories keep their modes, and tar creates any
# missing parent directory itself.
#
# It also rewrites the archive's etc/rc.local so the archive is re-armed
# only after a boot has finished (pcd started, plus two minutes). A boot that
# stalls then leaves nothing staged, and a power cycle brings the router
# back on stock firmware instead of repeating the failure.

set -e

check() {
  tar tzf "$1" > /tmp/fm-keeper.members || { echo "keeper-pack: $1 is not a readable tar.gz" >&2; return 1; }
  if grep -q '/$' /tmp/fm-keeper.members || grep -qx '\.' /tmp/fm-keeper.members; then
    echo "keeper-pack: $1 has directory entries; restoring it would change the modes of live directories:" >&2
    grep '/$' /tmp/fm-keeper.members | head -n 20 >&2
    rm -f /tmp/fm-keeper.members
    return 1
  fi
  if [ ! -s /tmp/fm-keeper.members ]; then
    echo "keeper-pack: $1 is empty" >&2; rm -f /tmp/fm-keeper.members; return 1
  fi
  if tar xzOf "$1" etc/rc.local 2>/dev/null | grep -q 'sysupgrade.tgz.real' &&
     ! tar xzOf "$1" etc/rc.local 2>/dev/null | grep -q 'fastmile-rearm begin'; then
    echo "keeper-pack: $1 has an rc.local that re-arms the archive before pcd starts" >&2
    rm -f /tmp/fm-keeper.members; return 1
  fi
  rm -f /tmp/fm-keeper.members
}

# Remove the old immediate re-seed (and any earlier fail-safe block), then
# put the fail-safe block in front of the first "exit 0".
fix_rclocal() {
  awk '
    { line[NR] = $0 }
    END {
      n = NR; i = 1; done = 0
      while (i <= n) {
        l = line[i]
        if (l == "# fastmile-rearm begin") {
          while (i <= n && line[i] != "# fastmile-rearm end") i++
          i++; continue
        }
        if (l == "# fastmile: 1restore deletes /data/sysupgrade.tgz after extracting it.") { i++; continue }
        if (l == "if [ -f /data/sysupgrade.tgz.real ]; then" &&
            line[i+1] ~ /^[ \t]*cp \/data\/sysupgrade\.tgz\.real \/data\/sysupgrade\.tgz$/ &&
            line[i+2] == "fi") { i += 3; continue }
        if (l == "exit 0" && !done) {
          print "# fastmile-rearm begin"
          print "# 1restore applies and deletes /data/sysupgrade.tgz at boot. Re-arm it only"
          print "# once this boot has finished (pcd started, plus two minutes), so a boot"
          print "# that stalls leaves nothing staged and a power cycle comes back stock."
          print "if [ -f /data/sysupgrade.tgz.real ]; then"
          print "  ("
          print "    n=0"
          print "    while [ ! -f /tmp/pcd_started ] && [ $n -lt 900 ]; do sleep 10; n=$((n + 10)); done"
          print "    if [ -f /tmp/pcd_started ]; then"
          print "      sleep 120"
          print "      [ -f /tmp/pcd_started ] &&"
          print "        cp /data/sysupgrade.tgz.real /data/sysupgrade.tgz.tmp &&"
          print "        mv /data/sysupgrade.tgz.tmp /data/sysupgrade.tgz && sync"
          print "    fi"
          print "  ) </dev/null >/dev/null 2>&1 &"
          print "fi"
          print "# fastmile-rearm end"
          done = 1
        }
        print l
        i++
      }
    }
  ' "$1" > "$1.new"
  grep -q 'fastmile-rearm begin' "$1.new" || { echo "keeper-pack: no 'exit 0' in $1" >&2; rm -f "$1.new"; return 1; }
  cat "$1.new" > "$1"
  rm -f "$1.new"
}

if [ "$1" = "--check" ]; then
  [ -n "$2" ] || { echo "usage: keeper-pack.sh --check FILE" >&2; exit 2; }
  check "$2" && echo "keeper-pack: $2 OK ($(tar tzf "$2" | wc -l) files, no directory entries)"
  exit
fi

STAGE=$1
OUT=$2
[ -d "$STAGE" ] && [ -n "$OUT" ] || { echo "usage: keeper-pack.sh STAGE OUT" >&2; exit 2; }

[ -f "$STAGE/etc/rc.local" ] && fix_rclocal "$STAGE/etc/rc.local"

(cd "$STAGE" && find . ! -type d | sed 's#^\./##') > /tmp/fm-keeper.list
[ -s /tmp/fm-keeper.list ] || { echo "keeper-pack: $STAGE has no files" >&2; exit 1; }
tar czf "$OUT.new" -C "$STAGE" -T /tmp/fm-keeper.list
rm -f /tmp/fm-keeper.list
check "$OUT.new" || { rm -f "$OUT.new"; exit 1; }
mv "$OUT.new" "$OUT"
