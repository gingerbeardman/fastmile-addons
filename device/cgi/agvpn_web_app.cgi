#!/bin/sh
# agvpn_web_app.cgi — AdGuard VPN status and control for the VPN page and xbar.
#
# Auth: the browser session (see below), or an X-AGVPN-Token header for the
# xbar plugin.
#
# GET  -> {"result":0,"status":{...},"locations":{"cli":[...],"ipsec":[...]},
#          "devices":[{"ip","mac","name","type"}...]}
#         ?locations=refresh re-reads the CLI location list.
# POST -> form fields: csrf_token (required), action=apply|enable|disable,
#         and for apply any of enabled=0|1 mode=cli|ipsec location=<name>
#         scope=all|devices devices=<ip,ip,...>
#         -> {"result":0,"status":{...}}
# Errors -> {"result":<negative>,"reason":"..."}; 401 when not logged in.
# Nothing from the request reaches a shell unquoted.

# lighttpd's worker has RLIMIT_NOFILE 256. procd_lock does exec 1000>lock, which
# then fails, so "/etc/init.d/agvpn restart" silently does nothing. Raise it
# (this process is root; children inherit it).
ulimit -n 1024 2>/dev/null || true

CT="Content-Type: application/json"
AG=/usr/sbin/agvpn
TMP=/tmp/agvpn-svc
mkdir -p $TMP

emit() { # body [status]
	[ -n "$2" ] && printf 'Status: %s\r\n' "$2"
	printf '%s\r\nCache-Control: no-store\r\n\r\n%s\n' "$CT" "$1"
}

field() {
	printf '%s' "$2" | tr '&' '\n' | sed -n "s/^$1=//p" | head -n 1 \
		| sed 's/+/ /g; s/%/\\x/g' | xargs -0 printf '%b' 2>/dev/null
}

[ -x $AG ] || { emit '{"result":-2,"reason":"agvpn not installed"}'; exit 0; }

# --- auth ---
# 1. X-AGVPN-Token header matching /data/adguardvpn-cli/api.token (for the xbar
#    plugin). The router allows only one web session at a time, so a menu-bar
#    tool that logged in would keep logging the browser out.
# 2. Otherwise the browser's session: the Cookie is forwarded to the stock
#    device_name_status_web_app.cgi, which answers 401 without a valid session.
#    Its device list is cached for token requests, which cannot fetch it.
DEV=$TMP/devices.$$
DEVCACHE=$TMP/devices.cache
TOKFILE=/data/adguardvpn-cli/api.token
trap 'rm -f $DEV' EXIT
AUTH=""
if [ -n "$HTTP_X_AGVPN_TOKEN" ] && [ -s $TOKFILE ] && [ "$HTTP_X_AGVPN_TOKEN" = "$(cat $TOKFILE)" ]; then
	AUTH=token
	cp $DEVCACHE $DEV 2>/dev/null || echo '{}' > $DEV
else
	code=$(curl -s -m 6 -H "Cookie: ${HTTP_COOKIE:-none}" -o $DEV -w '%{http_code}' \
		http://192.168.1.1/device_name_status_web_app.cgi 2>/dev/null)
	if [ "$code" != 200 ]; then
		emit '{"result":-401,"reason":"login required"}' "401 Unauthorized"
		exit 0
	fi
	AUTH=session
	cp $DEV $DEVCACHE.new 2>/dev/null && mv $DEVCACHE.new $DEVCACHE
fi

devices_json() {
	# Zip IP, MAC, HostName, InterfaceType; apply HostAlias where one is set.
	ips=$(jsonfilter -i $DEV -e '@.device_cfg[*].IPAddress' 2>/dev/null)
	[ -n "$ips" ] || { echo '[]'; return; }
	jsonfilter -i $DEV -e '@.device_cfg[*].MACAddress' > $TMP/d.mac.$$
	jsonfilter -i $DEV -e '@.device_cfg[*].HostName' > $TMP/d.name.$$
	jsonfilter -i $DEV -e '@.device_cfg[*].InterfaceType' > $TMP/d.type.$$
	jsonfilter -i $DEV -e '@.alias_cfg[*].HostName' > $TMP/a.name.$$ 2>/dev/null
	jsonfilter -i $DEV -e '@.alias_cfg[*].HostAlias' > $TMP/a.alias.$$ 2>/dev/null
	echo "$ips" | awk -v M=$TMP/d.mac.$$ -v N=$TMP/d.name.$$ -v T=$TMP/d.type.$$ \
		-v AN=$TMP/a.name.$$ -v AA=$TMP/a.alias.$$ '
		function clean(s) { gsub(/[\\"]/, "", s); gsub(/[\001-\037]/, "", s); return s }
		BEGIN {
			while ((getline a < AN) > 0) { getline b < AA; if (b != "") alias[a] = b }
		}
		{
			getline mac < M; getline name < N; getline type < T
			if (name in alias) name = alias[name]
			printf "%s{\"ip\":\"%s\",\"mac\":\"%s\",\"name\":\"%s\",\"type\":\"%s\"}", (n++ ? "," : "["), clean($0), clean(mac), clean(name), clean(type)
		}
		END { print (n ? "]" : "[]") }'
	rm -f $TMP/d.*.$$ $TMP/a.*.$$
}

status_json() { $AG status 2>/dev/null || echo '{}'; }

if [ "$REQUEST_METHOD" != POST ]; then
	case "$QUERY_STRING" in *locations=refresh*) r=refresh ;; *) r="" ;; esac
	cli=$($AG locations-mode cli $r 2>/dev/null)
	ipsec=$($AG locations-mode ipsec 2>/dev/null)
	emit "{\"result\":0,\"status\":$(status_json),\"locations\":{\"cli\":${cli:-[]},\"ipsec\":${ipsec:-[]}},\"devices\":$(devices_json)}"
	exit 0
fi

# --- POST ---
# Reject cross-site posts: if the browser sent an Origin or Referer, it must be ours.
for h in "$HTTP_ORIGIN" "$HTTP_REFERER"; do
	[ -z "$h" ] && continue
	case "$h" in http://192.168.1.1|http://192.168.1.1/*) ;; *) emit '{"result":-403,"reason":"bad origin"}' "403 Forbidden"; exit 0 ;; esac
done

cl=${CONTENT_LENGTH:-0}
case "$cl" in ''|*[!0-9]*) cl=0 ;; esac
[ "$cl" -gt 4096 ] && cl=4096
BODY=$(head -c "$cl")
# A token request carries a secret custom header that cross-site pages cannot send.
[ "$AUTH" = token ] || [ -n "$(field csrf_token "$BODY")" ] || { emit '{"result":-1,"reason":"missing csrf"}'; exit 0; }

action=$(field action "$BODY")
before=$(stat -c %Y $TMP/state.json 2>/dev/null; cat $TMP/state.json 2>/dev/null | md5sum)
case "$action" in
	enable)  $AG enable >/dev/null 2>&1 ;;
	disable) $AG disable >/dev/null 2>&1 ;;
	apply)
		set --
		v=$(field enabled "$BODY");  case "$v" in 0|1) set -- "$@" "enabled=$v" ;; esac
		v=$(field mode "$BODY");     case "$v" in cli|ipsec) set -- "$@" "mode=$v" ;; esac
		v=$(field location "$BODY"); [ -n "$v" ] && set -- "$@" "location=$(printf '%s' "$v" | tr -cd 'A-Za-z .()-' | head -c 40)"
		v=$(field scope "$BODY");    case "$v" in all|devices) set -- "$@" "scope=$v" ;; esac
		if printf '%s' "$BODY" | grep -q -E '(^|&)devices='; then
			v=$(field devices "$BODY" | tr -cd '0-9., ')
			set -- "$@" "devices=$v"
		fi
		$AG apply "$@" >/dev/null 2>&1 ;;
	*) emit '{"result":-1,"reason":"unknown action"}'; exit 0 ;;
esac
# Confirm the service reacted: state.json is rewritten on every stop/start.
i=0
while [ $i -lt 5 ]; do
	now=$(stat -c %Y $TMP/state.json 2>/dev/null; cat $TMP/state.json 2>/dev/null | md5sum)
	[ "$now" != "$before" ] && break
	sleep 1; i=$((i+1))
done
if [ "$now" = "$before" ]; then
	emit "{\"result\":-5,\"reason\":\"settings saved but the VPN service did not restart\",\"status\":$(status_json)}"
else
	emit "{\"result\":0,\"status\":$(status_json)}"
fi
