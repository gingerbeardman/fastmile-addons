#!/bin/sh
# speed_test_status_web_app.cgi — backend for the Diagnostics speed test page.
# The page posts StartSpeedTest and GetSpeedTestResult. Stock firmware handles
# those on service_function_web_app.cgi, which does not run a test on this unit.
# Two methods in main.*.js are patched to post here instead.
#
# /usr/bin/ookla is installed, but Nokia's embed configuration URL now returns
# 403 invalid access, so the CLI cannot start. The button instead measures the
# default-route interface with Cloudflare's public down/up endpoints and a
# ping to 1.1.1.1. Results use the same JSON shape Ookla's -f json uses, in
# bytes/s and milliseconds, and the parser below converts them for the page.
#
# Units the page already applies:
#   downloadbw and uploadbw are bits/s (shown as / 1e6)
#   pinglatency and pingjitter are microseconds (shown as / 1e3)
#   TestStatus is Ongoing, Completed, or Error
#   AcquiredTime is epoch milliseconds (Angular date pipe, format "medium")
#
# Ookla's JSON reports bandwidth in bytes/s and latency in milliseconds.
# No field from the request is passed to the shell.

STATE=/tmp/speedtest
HIST=/data/speedtest/history.jsonl
MAX_HIST=20

emit() {
  printf 'Content-Type: application/json\r\nCache-Control: no-store\r\n\r\n%s\n' "$1"
}

json_escape() {
  printf '%s' "$1" | awk 'BEGIN{ORS=""} {
    gsub(/\\/, "\\\\")
    gsub(/"/, "\\\"")
    gsub(/\r/, "")
    gsub(/\n/, " ")
    gsub(/\t/, " ")
    print
  }'
}

row() {
  # $1 status $2 down-bps $3 up-bps $4 lat-us $5 jit-us $6 location $7 acquired-ms
  # Quotes and backslashes are dropped from the location so emit_list can
  # copy it into Servers with a plain sed match.
  loc=$(json_escape "$(printf '%s' "$6" | tr -d '"\\')")
  printf '{"TestStatus":"%s","downloadbw":%s,"uploadbw":%s,"pinglatency":%s,"pingjitter":%s,"Location":"%s","AcquiredTime":%s}' \
    "$1" "${2:-0}" "${3:-0}" "${4:-0}" "${5:-0}" "$loc" "${7:-0}"
}

emit_list() {
  # The history table renders e.Servers[0].server.location. A row without
  # Servers throws in every change-detection pass, which leaves the privacy
  # dialog empty and impossible to close. Add it to every row here, so rows
  # already stored in the history file are covered too.
  list=$(printf '%s' "$1" | sed 's/"Location":"\([^"]*\)"/&,"Servers":[{"server":{"location":"\1"}}]/g')
  emit "{\"result\":0,\"FunctionResult\":{\"SpeedTestResultList\":[$list]}}"
}

alive() {
  [ -f "$1" ] || return 1
  pid=$(cat "$1" 2>/dev/null) || return 1
  case "$pid" in
    ''|*[!0-9]*) return 1 ;;
  esac
  kill -0 "$pid" 2>/dev/null
}

running() {
  alive "$STATE/worker.pid" || alive "$STATE/ookla.pid"
}

sed_field() {
  # $1 regex body is stdin. Prints the first capture.
  sed -n "$1" | head -n 1
}

parse_ookla() {
  # stdin: Ookla JSON (one object, or several lines). Prints one result row.
  raw=$(tr -d '\r\n')
  result=$(printf '%s' "$raw" | sed 's/.*"type"[[:space:]]*:[[:space:]]*"result"/{"type":"result"/')
  [ -n "$result" ] || result=$raw

  down=$(printf '%s' "$result" | sed_field 's/.*"download"[[:space:]]*:[[:space:]]*{[[:space:]]*"bandwidth"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p')
  up=$(printf '%s' "$result" | sed_field 's/.*"upload"[[:space:]]*:[[:space:]]*{[[:space:]]*"bandwidth"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p')
  ping=$(printf '%s' "$result" | sed_field 's/.*"ping"[[:space:]]*:[[:space:]]*{\([^}]*\)}.*/\1/p')
  lat=$(printf '%s' "$ping" | sed_field 's/.*"latency"[[:space:]]*:[[:space:]]*\([0-9.][0-9.]*\).*/\1/p')
  jit=$(printf '%s' "$ping" | sed_field 's/.*"jitter"[[:space:]]*:[[:space:]]*\([0-9.][0-9.]*\).*/\1/p')
  loc=$(printf '%s' "$result" | sed_field 's/.*"location"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
  country=$(printf '%s' "$result" | sed_field 's/.*"country"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
  isp=$(printf '%s' "$result" | sed_field 's/.*"isp"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')

  [ -n "$loc" ] && [ -n "$country" ] && loc="$loc, $country"
  [ -n "$loc" ] || loc=$isp

  down_bps=$(awk -v b="${down:-0}" 'BEGIN { printf "%.0f", b * 8 }')
  up_bps=$(awk -v b="${up:-0}" 'BEGIN { printf "%.0f", b * 8 }')
  lat_us=$(awk -v b="${lat:-0}" 'BEGIN { printf "%.0f", b * 1000 }')
  jit_us=$(awk -v b="${jit:-0}" 'BEGIN { printf "%.0f", b * 1000 }')
  now=$(date +%s 2>/dev/null || echo 0)
  case "$now" in
    ''|*[!0-9]*) now=0 ;;
  esac
  acquired=$((now * 1000))

  if [ -z "$down" ] && [ -z "$up" ]; then
    row Error 0 0 0 0 "" "$acquired"
    return 1
  fi
  row Completed "$down_bps" "$up_bps" "$lat_us" "$jit_us" "$loc" "$acquired"
  return 0
}

append_hist() {
  mkdir -p /data/speedtest
  printf '%s\n' "$1" >> "$HIST"
  tmp="$HIST.tmp"
  tail -n "$MAX_HIST" "$HIST" > "$tmp" 2>/dev/null && mv "$tmp" "$HIST"
}

history_json() {
  [ -f "$HIST" ] || return 0
  awk '{ a[NR] = $0 } END { for (i = NR; i >= 1; i--) print a[i] }' "$HIST" \
    | awk 'NF { printf "%s%s", (n++ ? "," : ""), $0 }'
}

default_iface() {
  iface=$(ip -4 route show default 2>/dev/null | awk '{
    for (i = 1; i <= NF; i++) if ($i == "dev") { print $(i + 1); exit }
  }')
  case "$iface" in
    ""|*[!A-Za-z0-9._-]*) return 0 ;;
  esac
  printf '%s' "$iface"
}

# Writes an Ookla-shaped result to $STATE/ookla.json. Bandwidth values are
# bytes/s. Returns 0 when both transfers moved some data.
measure() {
  iface=$(default_iface)
  set --
  [ -n "$iface" ] && set -- --interface "$iface"

  if [ -n "$iface" ]; then
    ping_out=$(ping -I "$iface" -c 8 -W 2 1.1.1.1 2>&1) || true
  else
    ping_out=$(ping -c 8 -W 2 1.1.1.1 2>&1) || true
  fi
  stats=$(printf '%s\n' "$ping_out" | awk '
    /time=/ {
      n = split($0, a, "time=")
      if (n >= 2) {
        split(a[2], b, " ")
        t[++nping] = b[1] + 0
      }
    }
    END {
      if (nping < 1) { print "0 0"; exit }
      sum = 0
      for (i = 1; i <= nping; i++) sum += t[i]
      avg = sum / nping
      jit = 0
      if (nping > 1) {
        d = 0
        for (i = 2; i <= nping; i++) {
          diff = t[i] - t[i - 1]
          if (diff < 0) diff = -diff
          d += diff
        }
        jit = d / (nping - 1)
      }
      printf "%.3f %.3f\n", avg, jit
    }
  ')
  lat=$(printf '%s' "$stats" | awk '{ print $1 }')
  jit=$(printf '%s' "$stats" | awk '{ print $2 }')
  [ -n "$lat" ] || lat=0
  [ -n "$jit" ] || jit=0

  # A single huge request is rejected. Four 25 MB transfers is the cap.
  : > "$STATE/dl.samples"
  for _ in 1 2 3 4; do
    dl=$(curl -sS -m 8 -o /dev/null "$@" -w '%{size_download} %{time_total}' \
      "https://speed.cloudflare.com/__down?bytes=25000000" 2>>"$STATE/down.err") || true
    printf '%s\n' "$dl" >> "$STATE/dl.samples"
  done
  dl_bytes=$(awk '{ s += $1 } END { printf "%.0f", s + 0 }' "$STATE/dl.samples")
  dl_bps=$(awk '{ b += $1; t += $2 } END {
    if (t + 0 <= 0) print 0; else printf "%.0f", b / t
  }' "$STATE/dl.samples")

  dd if=/dev/zero of="$STATE/payload" bs=1024 count=20480 >/dev/null 2>&1 || true
  ul=$(curl -sS -m 15 -o /dev/null "$@" -w '%{size_upload} %{time_total}' \
    -X POST --data-binary @"$STATE/payload" https://speed.cloudflare.com/__up \
    2>"$STATE/up.err") || true
  rm -f "$STATE/payload"
  ul_bytes=$(printf '%s' "$ul" | awk '{ print $1 }')
  ul_time=$(printf '%s' "$ul" | awk '{ print $2 }')
  ul_bps=$(awk -v b="${ul_bytes:-0}" -v t="${ul_time:-0}" 'BEGIN {
    if (t + 0 <= 0) print 0; else printf "%.0f", b / t
  }')

  # ISP and country only. The config document also contains the WAN address;
  # it stays in this process and is not written out.
  xml=$(curl -sS -m 10 "$@" https://www.speedtest.net/speedtest-config.php 2>/dev/null) || xml=""
  isp=$(printf '%s' "$xml" | sed -n 's/.* isp="\([^"]*\)".*/\1/p' | head -n 1)
  country=$(printf '%s' "$xml" | sed -n 's/.* country="\([^"]*\)".*/\1/p' | head -n 1)
  xml=""
  [ -n "$isp" ] || isp="Cloudflare"
  isp_j=$(json_escape "$isp")
  country_j=$(json_escape "$country")

  printf '{"type":"result","ping":{"jitter":%s,"latency":%s},"download":{"bandwidth":%s},"upload":{"bandwidth":%s},"isp":"%s","server":{"location":"Cloudflare","country":"%s"}}\n' \
    "$jit" "$lat" "${dl_bps:-0}" "${ul_bps:-0}" \
    "$isp_j" "$country_j" > "$STATE/ookla.json"

  [ "${dl_bytes:-0}" -gt 100000 ] 2>/dev/null && [ "${ul_bytes:-0}" -gt 100000 ] 2>/dev/null
}

worker() {
  mkdir -p "$STATE" /data/speedtest
  echo $$ > "$STATE/worker.pid"
  echo running > "$STATE/status"
  trap '' HUP

  measure
  rc=$?
  echo "$rc" > "$STATE/rc"
  rm -f "$STATE/ookla.pid"
  echo finishing > "$STATE/status"

  now=$(date +%s 2>/dev/null || echo 0)
  case "$now" in
    ''|*[!0-9]*) now=0 ;;
  esac
  acquired=$((now * 1000))

  parsed=""
  if [ "$rc" -eq 0 ] && [ -s "$STATE/ookla.json" ]; then
    parsed=$(parse_ookla < "$STATE/ookla.json") && parse_ok=1 || parse_ok=0
  else
    parse_ok=0
  fi
  if [ "$parse_ok" = 1 ]; then
    printf '%s\n' "$parsed" > "$STATE/latest.json"
    append_hist "$parsed"
  else
    row Error 0 0 0 0 "" "$acquired" > "$STATE/latest.json"
  fi

  echo done > "$STATE/status"
  rm -f "$STATE/worker.pid"
  rm -rf "$STATE/start.lockdir"
}

finish_if_dead() {
  # A worker that vanished without writing a result becomes an error row.
  [ -f "$STATE/status" ] || return 0
  [ "$(cat "$STATE/status" 2>/dev/null)" = "running" ] || return 0
  running && return 0
  now=$(date +%s 2>/dev/null || echo 0)
  case "$now" in
    ''|*[!0-9]*) now=0 ;;
  esac
  row Error 0 0 0 0 "" "$((now * 1000))" > "$STATE/latest.json"
  echo done > "$STATE/status"
  rm -f "$STATE/worker.pid" "$STATE/ookla.pid" "$STATE/start.lockdir"
}

do_start() {
  if ! command -v curl >/dev/null 2>&1; then
    emit '{"result":-1,"reason":"curl is not installed"}'
    return 0
  fi
  mkdir -p "$STATE"
  if running; then
    emit '{"result":0}'
    return 0
  fi
  # A lock left by a dead worker must not block the next run.
  rm -rf "$STATE/start.lockdir"
  if ! mkdir "$STATE/start.lockdir" 2>/dev/null; then
    emit '{"result":0}'
    return 0
  fi
  rm -f "$STATE/ookla.pid" "$STATE/latest.json"
  echo running > "$STATE/status"
  # sh, not a direct exec: /webs may be noexec after a future mount change.
  nohup sh "$0" --worker >/dev/null 2>"$STATE/worker.err" &
  echo $! > "$STATE/worker.pid"
  emit '{"result":0}'
}

do_get() {
  finish_if_dead
  ongoing=$(row Ongoing 0 0 0 0 "" 0)
  if running || [ "$(cat "$STATE/status" 2>/dev/null)" = "running" ] \
    || [ "$(cat "$STATE/status" 2>/dev/null)" = "finishing" ]; then
    if [ "$1" = "true" ]; then
      rest=$(history_json)
      if [ -n "$rest" ]; then
        emit_list "$ongoing,$rest"
      else
        emit_list "$ongoing"
      fi
    else
      emit_list "$ongoing"
    fi
    return 0
  fi

  if [ "$1" = "true" ]; then
    rest=$(history_json)
    if [ -n "$rest" ]; then
      emit_list "$rest"
    else
      emit_list "$(row Error 0 0 0 0 "" -1)"
    fi
    return 0
  fi

  if [ -s "$STATE/latest.json" ]; then
    emit_list "$(cat "$STATE/latest.json")"
  else
    emit_list "$(row N/A 0 0 0 0 "N/A" -1)"
  fi
}

selftest() {
  sample='{"type":"result","timestamp":"2024-06-01T12:00:00Z","ping":{"jitter":1.25,"latency":18.4},"download":{"bandwidth":12500000,"bytes":1,"elapsed":1},"upload":{"bandwidth":5000000,"bytes":1,"elapsed":1},"isp":"Example","server":{"name":"Lab","location":"Sydney","country":"Australia"}}'
  got=$(printf '%s' "$sample" | parse_ookla) || { echo "parse failed: $got" >&2; exit 1; }
  printf '%s' "$got" | grep -q '"TestStatus":"Completed"' || { echo "status: $got" >&2; exit 1; }
  printf '%s' "$got" | grep -q '"downloadbw":100000000' || { echo "down: $got" >&2; exit 1; }
  printf '%s' "$got" | grep -q '"uploadbw":40000000' || { echo "up: $got" >&2; exit 1; }
  printf '%s' "$got" | grep -q '"pinglatency":18400' || { echo "lat: $got" >&2; exit 1; }
  printf '%s' "$got" | grep -q '"pingjitter":1250' || { echo "jit: $got" >&2; exit 1; }
  printf '%s' "$got" | grep -q '"Location":"Sydney, Australia"' || { echo "loc: $got" >&2; exit 1; }
  pretty='{ "type" : "result", "ping" : { "jitter" : 2.5, "latency" : 10 }, "download" : { "bandwidth" : 100 }, "upload" : { "bandwidth" : 50 }, "server" : { "location" : "Auckland", "country" : "NZ" } }'
  got=$(printf '%s' "$pretty" | parse_ookla) || { echo "pretty failed: $got" >&2; exit 1; }
  printf '%s' "$got" | grep -q '"downloadbw":800' || { echo "pretty down: $got" >&2; exit 1; }
  printf '%s' "$got" | grep -q '"Location":"Auckland, NZ"' || { echo "pretty loc: $got" >&2; exit 1; }
  out=$(emit_list "$(row Completed 1 2 3 4 'Lon"don' 5),$(row Ongoing 0 0 0 0 "" 0)")
  printf '%s' "$out" | grep -q '"Location":"London","Servers":\[{"server":{"location":"London"}}\]' \
    || { echo "servers: $out" >&2; exit 1; }
  printf '%s' "$out" | grep -q '"Location":"","Servers":\[{"server":{"location":""}}\]' \
    || { echo "servers empty: $out" >&2; exit 1; }
  echo "selftest ok"
}

case "$1" in
  --worker) worker; exit 0 ;;
  --selftest) selftest; exit 0 ;;
esac

if [ "$REQUEST_METHOD" != "POST" ]; then
  emit '{"result":-1,"reason":"POST required"}'
  exit 0
fi

cl=${CONTENT_LENGTH:-0}
case "$cl" in
  ''|*[!0-9]*) cl=0 ;;
esac
[ "$cl" -gt 8192 ] && cl=8192
BODY=$(head -c "$cl")

token=$(printf '%s' "$BODY" | sed_field 's/.*"csrf_token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
if [ -z "$token" ]; then
  emit '{"result":-1,"reason":"missing csrf"}'
  exit 0
fi

fn=$(printf '%s' "$BODY" | sed_field 's/.*"function"[[:space:]]*:[[:space:]]*"\([A-Za-z]*\)".*/\1/p')
hist=$(printf '%s' "$BODY" | sed_field 's/.*"History"[[:space:]]*:[[:space:]]*"\([a-zA-Z]*\)".*/\1/p')

case "$fn" in
  StartSpeedTest) do_start ;;
  GetSpeedTestResult) do_get "$hist" ;;
  *) emit '{"result":-1,"reason":"unknown function"}' ;;
esac
