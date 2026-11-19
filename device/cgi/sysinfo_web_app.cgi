#!/bin/sh
# sysinfo_web_app.cgi — router CPU, load, memory and uptime for Status → General.
#
# Reads /proc only (stat, loadavg, meminfo, uptime). It never asks the modem:
# querying X_ALU-COM_ModemDeviceInfo through cfgcli stalled for minutes and was
# followed by a watchdog reset (2026-11-19).
#
# GET -> {"result":0,"cpu":{"pct":12.3,"cores":[..],"n":4},
#         "load":[l1,l5,l15],"load_raw":[..],"load_base":8,
#         "procs":{"run":1,"total":180},
#         "mem":{"total":kB,"avail":kB,"free":kB,"cached":kB},
#         "swap":{"total":kB,"free":kB},"uptime":secs}
# 401 when not logged in. Takes about 1 s (two CPU samples).
#
# "load" has the board's permanently blocked kernel threads taken off.
# Linux counts every task in state D as 1 load. On this MediaTek board eight
# kernel threads sit in D all the time without using CPU: the watchdog kickers
# (wdtk-N, one per core), the Wi-Fi/Ethernet offload engine (wed_taskN), the
# modem link (ccci_pollN) and interrupt polling (isr_count_polli*), so raw
# load never drops below about 8. They are counted by name on each request,
# so the figure stays right if firmware changes them. "load_raw" is untouched.

CT="Content-Type: application/json"
emit() { # body [status]
	[ -n "$2" ] && printf 'Status: %s\r\n' "$2"
	printf '%s\r\nCache-Control: no-store\r\n\r\n%s\n' "$CT" "$1"
}

# --- auth: forward the browser's Cookie to a stock CGI that answers 401 without
# a valid session (same check as agvpn_web_app.cgi). FM_SYSINFO_NOAUTH is for
# the Docker test only; lighttpd never sets it.
if [ -z "$FM_SYSINFO_NOAUTH" ]; then
	code=$(curl -s -m 6 -H "Cookie: ${HTTP_COOKIE:-none}" -o /dev/null -w '%{http_code}' \
		http://192.168.1.1/device_name_status_web_app.cgi 2>/dev/null)
	if [ "$code" != 200 ]; then
		emit '{"result":-401,"reason":"login required"}' "401 Unauthorized"
		exit 0
	fi
fi

PROC=${FM_SYSINFO_PROC:-/proc}
# One awk over every status file; a task that exits mid-read is just skipped.
BASE=$(awk '/^Name:/ { n = $2 }
	/^State:/ { if ($2 == "D" && n ~ /^(wdtk-[0-9]+|wed_task[0-9]+|ccci_poll[0-9]*|isr_count_polli.*)$/) c++ }
	END { print c + 0 }' $PROC/[0-9]*/status 2>/dev/null)
S1=$(grep '^cpu' $PROC/stat)
sleep 1
S2=$(grep '^cpu' $PROC/stat)

body=$(printf '%s\n--\n%s\n' "$S1" "$S2" | awk -v P="$PROC" -v B="${BASE:-0}" '
	# busy = all ticks except idle + iowait; pct = delta busy / delta total
	function rd(line,  f, n, i, t, idle) {
		n = split(line, f, " "); t = 0
		for (i = 2; i <= n; i++) t += f[i]
		idle = f[5] + (n >= 6 ? f[6] : 0)
		T = t; I = idle; return f[1]
	}
	$0 == "--" { second = 1; next }
	!/^cpu/ { next }
	{ k = rd($0); if (!second) { t0[k] = T; i0[k] = I; order[++nk] = k } else { t1[k] = T; i1[k] = I } }
	END {
		for (j = 1; j <= nk; j++) {
			k = order[j]; dt = t1[k] - t0[k]; di = i1[k] - i0[k]
			p = (dt > 0) ? 100 * (dt - di) / dt : 0
			if (p < 0) p = 0; if (p > 100) p = 100
			if (k == "cpu") tot = sprintf("%.1f", p)
			else { cores = cores (nc++ ? "," : "") sprintf("%.1f", p) }
		}
		getline la < (P "/loadavg"); split(la, L, " "); split(L[4], R, "/")
		while ((getline m < (P "/meminfo")) > 0) { split(m, a, "[: ]+"); M[a[1]] = a[2] }
		getline up < (P "/uptime"); split(up, U, " ")
		av = (M["MemAvailable"] != "") ? M["MemAvailable"] : M["MemFree"] + M["Buffers"] + M["Cached"]
		printf "{\"result\":0,\"cpu\":{\"pct\":%s,\"cores\":[%s],\"n\":%d},", tot + 0, cores, nc
		for (j = 1; j <= 3; j++) { A[j] = L[j] - B; if (A[j] < 0) A[j] = 0 }
		printf "\"load\":[%.2f,%.2f,%.2f],\"load_raw\":[%s,%s,%s],\"load_base\":%d,", A[1], A[2], A[3], L[1] + 0, L[2] + 0, L[3] + 0, B
		printf "\"procs\":{\"run\":%d,\"total\":%d},", R[1], R[2]
		printf "\"mem\":{\"total\":%d,\"avail\":%d,\"free\":%d,\"cached\":%d},", M["MemTotal"], av, M["MemFree"], M["Cached"] + M["Buffers"]
		printf "\"swap\":{\"total\":%d,\"free\":%d},\"uptime\":%d}", M["SwapTotal"], M["SwapFree"], U[1]
	}')

emit "$body"
