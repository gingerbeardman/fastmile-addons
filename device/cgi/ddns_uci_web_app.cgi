#!/bin/sh
# ddns_uci_web_app.cgi — minimal UCI-backed DDNS endpoint for the custom UI.
# Deploy to the device web root (served by lighttpd as a CGI). Reads/writes the
# standard OpenWrt ddns-scripts config at /etc/config/ddns and (re)starts the
# updater. Talks the same JSON shape as the mock dev server.
#
# GET  -> {"enabled","service_name","domain","username","interface","status"}
# POST (x-www-form-urlencoded: enabled,service_name,domain,username,password,
#       interface,csrf_token) -> {"result":0,"status":"..."}
#
# The cellular address is private. The public address is read from the
# internet (ip_source=web) and the update is sent out ltewan. wan and wan6
# are not networks on this gateway. Status is taken from the updater log,
# not from the DNS lookup file, which is written before any update is sent.
#
# NOTE: session/csrf validation below is a placeholder. Harden against the live
# /tmp/cgi_session store once root access confirms its format. LAN-only.

# lighttpd's nofile limit is 256. procd's lock fd needs a higher ceiling.
ulimit -n 1024 2>/dev/null || true

SECTION="myddns"            # the ddns service section we manage
CT="Content-Type: application/json"
# Bare address. grep takes the first IPv4. HTTPS so the body is only the address.
IP_URL="https://ipv4.icanhazip.com/"

emit() { printf '%s\r\n\r\n%s' "$CT" "$1"; }

# usage: field <name> <body>
# encodeURIComponent on the page. Decode once. Do not pass the result through
# printf %b: a password containing a backslash would be interpreted again.
field() {
  printf '%s' "$2" | awk -v key="$1" '
    BEGIN { h = "0123456789ABCDEF" }
    function dec(s,   i, c, o, a, b, hh) {
      o = ""
      i = 1
      while (i <= length(s)) {
        c = substr(s, i, 1)
        if (c == "+") { o = o " "; i++; continue }
        if (c == "%" && i + 2 <= length(s)) {
          hh = toupper(substr(s, i + 1, 2))
          a = index(h, substr(hh, 1, 1))
          b = index(h, substr(hh, 2, 1))
          if (a && b) {
            o = o sprintf("%c", (a - 1) * 16 + (b - 1))
            i += 3
            continue
          }
        }
        o = o c
        i++
      }
      return o
    }
    {
      n = split($0, parts, "&")
      for (i = 1; i <= n; i++) {
        eq = index(parts[i], "=")
        if (eq == 0) continue
        if (substr(parts[i], 1, eq - 1) == key) {
          printf "%s", dec(substr(parts[i], eq + 1))
          exit
        }
      }
    }
  '
}

uci_get() { uci -q get "ddns.$SECTION.$1" 2>/dev/null; }

pid_alive() {
  pf="/var/run/ddns/$SECTION.pid"
  [ -f "$pf" ] || return 1
  pid=$(cat "$pf" 2>/dev/null) || return 1
  [ -n "$pid" ] || return 1
  kill -0 "$pid" 2>/dev/null
}

# Last matching outcome only. Never echo a log line: the transfer trace can
# contain the provider URL.
read_status() {
  en=$(uci_get enabled)
  [ "$en" = "1" ] || { echo "Disabled"; return; }
  log="/var/log/ddns/$SECTION.log"
  line=""
  if [ -f "$log" ]; then
    line=$(grep -E 'Forced update successful|Update successful|not accepted by DDNS|Can not detect local IP|TERMINATE' "$log" 2>/dev/null | tail -n 1)
  fi
  case "$line" in
    *"not accepted"*)
      echo "Update rejected"
      return
      ;;
    *"Update successful"*|*"Forced update successful"*)
      ip=$(printf '%s\n' "$line" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' | head -n 1)
      if pid_alive; then
        if [ -n "$ip" ]; then echo "Updated: $ip"; else echo "Updated"; fi
      else
        if [ -n "$ip" ]; then echo "Updated: $ip (updater stopped)"; else echo "Updated (updater stopped)"; fi
      fi
      return
      ;;
    *"Can not detect"*|*"TERMINATE"*)
      echo "Updater failed"
      return
      ;;
  esac
  if pid_alive; then echo "Checking"; else echo "Updater stopped"; fi
}

json_get() {
  printf '{"enabled":"%s","service_name":"%s","domain":"%s","username":"%s","interface":"%s","status":"%s"}' \
    "$(uci_get enabled)" "$(uci_get service_name)" "$(uci_get domain)" \
    "$(uci_get username)" "$(uci_get interface)" "$(read_status)"
}

if [ "$REQUEST_METHOD" = "POST" ]; then
  BODY=$(head -c "${CONTENT_LENGTH:-0}")

  # TODO(root): validate csrf_token against the live session token store.
  CSRF=$(field csrf_token "$BODY")
  [ -n "$CSRF" ] || { emit '{"result":-3,"reason":"no csrf"}'; exit 0; }

  EN=$(field enabled "$BODY");        SV=$(field service_name "$BODY")
  DM=$(field domain "$BODY");         UN=$(field username "$BODY")
  PW=$(field password "$BODY");       IF=$(field interface "$BODY")

  # wan/wan6 are not UCI networks here. Anything unknown falls back to cellular.
  case "$IF" in
    ""|wan|wan6) IF="ltewan" ;;
  esac
  printf '%s' "$IF" | grep -q '^[A-Za-z0-9_]\{1,16\}$' || IF="ltewan"
  uci -q get "network.$IF" >/dev/null 2>&1 || IF="ltewan"

  # ensure the section exists
  [ "$(uci -q get ddns.$SECTION)" = "service" ] || uci set "ddns.$SECTION=service"

  uci set "ddns.$SECTION.enabled=${EN:-0}"
  [ -n "$SV" ] && uci set "ddns.$SECTION.service_name=$SV"
  [ -n "$DM" ] && { uci set "ddns.$SECTION.domain=$DM"; uci set "ddns.$SECTION.lookup_host=$DM"; }
  [ -n "$UN" ] && uci set "ddns.$SECTION.username=$UN"
  [ -n "$PW" ] && uci set "ddns.$SECTION.password=$PW"   # only when provided
  uci set "ddns.$SECTION.interface=$IF"
  uci set "ddns.$SECTION.bind_network=$IF"
  uci set "ddns.$SECTION.ip_source=web"
  uci set "ddns.$SECTION.ip_url=$IP_URL"
  uci set "ddns.$SECTION.use_ipv6=0"
  uci set "ddns.$SECTION.retry_count=5"
  uci -q delete "ddns.$SECTION.ip_network"
  uci commit ddns
  # /etc/config is on the tmpfs overlay and dies at reboot. Keep a copy on /data.
  mkdir -p /data/config
  cp /etc/config/ddns /data/config/ddns
  chmod 600 /data/config/ddns

  if [ "${EN:-0}" = "1" ]; then
    # Count first. A fast run can log the result before restart returns.
    log="/var/log/ddns/$SECTION.log"
    mark=0
    [ -f "$log" ] && mark=$(wc -l < "$log")
    /etc/init.d/ddns restart >/dev/null 2>&1
    now=0
    [ -f "$log" ] && now=$(wc -l < "$log")
    [ "$now" -lt "$mark" ] && mark=0
    i=0
    while [ "$i" -lt 25 ]; do
      if [ -f "$log" ] && tail -n +$((mark + 1)) "$log" 2>/dev/null \
          | grep -q -E 'Update successful|Forced update successful|not accepted by DDNS|Can not detect local IP|TERMINATE'; then
        break
      fi
      sleep 1
      i=$((i + 1))
    done
  else
    /etc/init.d/ddns stop >/dev/null 2>&1
  fi

  emit "$(printf '{"result":0,"status":"%s"}' "$(read_status)")"
  exit 0
fi

# default: GET
emit "$(json_get)"
