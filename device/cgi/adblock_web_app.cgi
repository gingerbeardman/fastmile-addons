#!/bin/sh
# adblock_web_app.cgi — status and toggle for OpenWrt adblock 4.1.
# GET  -> installed, enabled, runtime summary, blocklist catalog
# POST -> save (enabled + selected sources), refresh, or query a domain
# Source names are checked against the catalog. Nothing from the request
# is passed to a shell unquoted.

# lighttpd's worker has RLIMIT_NOFILE 256. procd_lock does exec 1000>lock,
# and busybox ash then fails with "Bad file descriptor", so the init action
# never runs. This process is root and can raise the limit. Children inherit
# it, including the dnsmasq restart that adblock performs.
ulimit -n 1024 2>/dev/null || true

CT="Content-Type: application/json"
SRC=/etc/adblock/adblock.sources.gz
RT=/tmp/adb_runtime.json
CFG=/etc/config/adblock

emit() { printf '%s\r\nCache-Control: no-store\r\n\r\n%s\n' "$CT" "$1"; }

json_escape() {
  printf '%s' "$1" | awk 'BEGIN{ORS=""} {
    gsub(/\\/, "\\\\")
    gsub(/"/, "\\\"")
    gsub(/\r/, "")
    gsub(/\n/, "\\n")
    gsub(/\t/, " ")
    print
  }'
}

field() {
  printf '%s' "$2" | tr '&' '\n' | sed -n "s/^$1=//p" | head -n 1 \
    | sed 's/+/ /g; s/%/\\x/g' | xargs -0 printf '%b' 2>/dev/null
}

installed() {
  [ -x /usr/bin/adblock.sh ] && [ -f "$SRC" ] && [ -x /etc/init.d/adblock ]
}

gnu_sort() {
  sort --version 2>/dev/null | grep -q coreutils
}

# Prints a JSON array of {name,size,focus,enabled}.
sources_json() {
  selected=" $(uci -q get adblock.global.adb_sources 2>/dev/null) "
  gzip -dc "$SRC" 2>/dev/null | awk -v sel="$selected" '
    function emit(name, size, focus) {
      if (name == "") return
      on = (index(sel, " " name " ") > 0) ? "true" : "false"
      printf "%s{\"name\":\"%s\",\"size\":\"%s\",\"focus\":\"%s\",\"enabled\":%s}",
        (n++ ? "," : ""), name, size, focus, on
    }
    {
      line = $0
      if (line ~ /^[ \t]*"[a-z0-9_]+":[ \t]*\{[ \t]*$/) {
        if (name != "") emit(name, size, focus)
        sub(/^[ \t]*"/, "", line)
        sub(/":[ \t]*\{[ \t]*$/, "", line)
        name = line
        size = ""
        focus = ""
      } else if (line ~ /"size":/) {
        gsub(/.*"size":[ \t]*"/, "", line)
        gsub(/".*/, "", line)
        size = line
      } else if (line ~ /"focus":/) {
        gsub(/.*"focus":[ \t]*"/, "", line)
        gsub(/".*/, "", line)
        focus = line
      }
    }
    END { if (name != "") emit(name, size, focus) }
  '
}

rt() {
  [ -f "$RT" ] || return 0
  jsonfilter -i "$RT" -e "$1" 2>/dev/null
}

running() {
  pid=$(cat /var/run/adblock.pid 2>/dev/null) || return 1
  case "$pid" in
    ''|*[!0-9]*) return 1 ;;
  esac
  kill -0 "$pid" 2>/dev/null
}

do_get() {
  if ! installed; then
    emit '{"installed":false,"enabled":"0","status":"not installed","sources":[]}'
    return 0
  fi
  en=$(uci -q get adblock.global.adb_enabled 2>/dev/null)
  [ -n "$en" ] || en=0
  st=$(rt '@.adblock_status')
  [ -n "$st" ] || st="stopped"
  ver=$(rt '@.adblock_version')
  cnt=$(rt '@.blocked_domains')
  last=$(rt '@.last_run')
  dns=$(rt '@.dns_backend')
  run=false
  running && run=true
  sort_ok=false
  gnu_sort && sort_ok=true
  emit "$(printf '{"installed":true,"enabled":"%s","status":"%s","version":"%s","blocked_domains":"%s","last_run":"%s","dns_backend":"%s","running":%s,"sort_ok":%s,"sources":[%s]}' \
    "$(json_escape "$en")" "$(json_escape "$st")" "$(json_escape "$ver")" \
    "$(json_escape "$cnt")" "$(json_escape "$last")" "$(json_escape "$dns")" \
    "$run" "$sort_ok" "$(sources_json)")"
}

known_source() {
  gzip -dc "$SRC" 2>/dev/null | grep -q "^[[:space:]]*\"$1\"[[:space:]]*:[[:space:]]*{"
}

apply_sources() {
  uci -q delete adblock.global.adb_sources
  rest=$1
  while [ -n "$rest" ]; do
    name=${rest%%,*}
    if [ "$name" = "$rest" ]; then rest=""; else rest=${rest#*,}; fi
    case "$name" in
      ""|*[!a-z0-9_]*) continue ;;
    esac
    known_source "$name" || continue
    uci add_list adblock.global.adb_sources="$name"
  done
}

save_cfg() {
  mkdir -p /data/config
  cp "$CFG" /data/config/adblock
  chmod 600 /data/config/adblock
}

do_save() {
  en=$1
  case "$en" in
    1) ;;
    *) en=0 ;;
  esac
  uci -q get adblock.global >/dev/null 2>&1 || uci set adblock.global=adblock
  uci set adblock.global.adb_enabled="$en"
  uci set adblock.global.adb_dns='dnsmasq'
  uci set adblock.global.adb_fetchutil='curl'
  uci set adblock.global.adb_backup='0'
  apply_sources "$2"
  uci commit adblock
  save_cfg
  if [ "$en" = "1" ]; then
    /etc/init.d/adblock enable
    /etc/init.d/adblock restart >/tmp/adblock-ui.log 2>&1
    emit '{"result":0,"status":"started"}'
  else
    /etc/init.d/adblock stop >/tmp/adblock-ui.log 2>&1
    /etc/init.d/adblock disable
    emit '{"result":0,"status":"stopped"}'
  fi
}

do_refresh() {
  en=$(uci -q get adblock.global.adb_enabled 2>/dev/null)
  if [ "$en" != "1" ]; then
    emit '{"result":-1,"reason":"adblock is off"}'
    return 0
  fi
  /etc/init.d/adblock enable
  /etc/init.d/adblock restart >/tmp/adblock-ui.log 2>&1
  emit '{"result":0,"status":"started"}'
}

do_query() {
  dom=$1
  case "$dom" in
    ""|*[!A-Za-z0-9.-]*|*.*.*.*.*.*.*) emit '{"result":-1,"reason":"bad domain"}'; return 0 ;;
  esac
  [ "${#dom}" -gt 253 ] && { emit '{"result":-1,"reason":"bad domain"}'; return 0; }
  out=$(/etc/init.d/adblock query "$dom" 2>&1 | head -c 4000)
  emit "$(printf '{"result":0,"output":"%s"}' "$(json_escape "$out")")"
}

if ! installed; then
  if [ "$REQUEST_METHOD" = "POST" ]; then
    emit '{"result":-1,"reason":"adblock is not installed"}'
  else
    do_get
  fi
  exit 0
fi

if [ "$REQUEST_METHOD" != "POST" ]; then
  do_get
  exit 0
fi

cl=${CONTENT_LENGTH:-0}
case "$cl" in
  ''|*[!0-9]*) cl=0 ;;
esac
[ "$cl" -gt 8192 ] && cl=8192
BODY=$(head -c "$cl")
csrf=$(field csrf_token "$BODY")
if [ -z "$csrf" ]; then
  emit '{"result":-1,"reason":"missing csrf"}'
  exit 0
fi

action=$(field action "$BODY")
case "$action" in
  save) do_save "$(field enabled "$BODY")" "$(field sources "$BODY")" ;;
  refresh) do_refresh ;;
  query) do_query "$(field domain "$BODY")" ;;
  *) emit '{"result":-1,"reason":"unknown action"}' ;;
esac
