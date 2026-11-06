#!/usr/bin/env python3
"""FastMile 5G Gateway 3.2 client: login + settings snapshot + raw CGI calls.
Reimplements the web_whw Angular login (jsencrypt/sjcl) challenge-response.
Usage:
  NOKIA=<pw> python3 -I fm.py snapshot          # read-only dump of every UI status page
  NOKIA=<pw> python3 -I fm.py get <endpoint>    # GET one cgi, print body
  NOKIA=<pw> python3 -I fm.py post <endpoint> <body>  # POST (csrf_token auto-added)

NOTE ON BACKUP/RESTORE
  `snapshot` is a HUMAN-READABLE record, not a restorable backup: it just GETs
  the status CGIs the web UI reads. The firmware's own "Restore or Backup DB"
  export (usb_web_app.cgi?export/import) is orphaned on software 1.2202.00.0287
  -- the UI references it but the CGI returns 404, so there is no web-based
  config export to capture. A real, restorable backup is the device's /data
  overlay, which requires a root shell: see client/fmbackup.py.

Env: FM_HOST (or FM_WEB_URL, default http://192.168.1.1), FM_USER (or
FM_WEB_USER, default admin), NOKIA (or FM_WEB_PASS) for the password.
Note: the router allows one web session at a time, so logging in here logs
out any browser tab.
"""
import os, re, sys, json, time, hashlib, base64, http.cookiejar, urllib.request as U

HOST = os.environ.get("FM_HOST") or os.environ.get("FM_WEB_URL") or "http://192.168.1.1"
HOST = HOST.rstrip("/")
USER = os.environ.get("FM_USER") or os.environ.get("FM_WEB_USER") or "admin"   # "superadmin" for the hidden ACS page
PW   = os.environ.get("NOKIA") or os.environ.get("FM_WEB_PASS")

def b64(b):  return base64.b64encode(b).decode()
def esc(s):  return s.replace("+","-").replace("/","_").replace("=",".")
def sha256_b64(a, b):            # cryptoJS.sha256(a,b) = base64(sha256("a:b"))
    return b64(hashlib.sha256(f"{a}:{b}".encode()).digest())
def sha256url(a, b):             # cryptoJS.sha256url
    return esc(sha256_b64(a, b))

cj = http.cookiejar.CookieJar()
opener = U.build_opener(U.HTTPCookieProcessor(cj))
TOKEN = {"v": None}

def req_raw(path, data=None, headers=None, timeout=12):
    url = HOST + "/" + path.lstrip("/")
    r = U.Request(url, data=data.encode() if isinstance(data, str) else data,
                  headers=headers or {})
    with opener.open(r, timeout=timeout) as resp:
        return resp.status, resp.headers, resp.read()

def req(path, data=None, headers=None):
    st, _, body = req_raw(path, data, headers)
    return st, body.decode("utf-8", "replace")

def login():
    if not PW:
        sys.exit("NOKIA (or FM_WEB_PASS) env var (web UI password) not set")
    _, body = req("login_web_app.cgi?nonce")
    n = json.loads(body)
    nonce, rkey, iters = n["nonce"], n["randomKey"], int(n.get("iterations", 1))
    l = hashlib.sha256(PW.encode()).hexdigest() if iters >= 1 else PW
    for _ in range(1, iters):    # extra rounds if iterations>1
        l = hashlib.sha256(bytes.fromhex(l)).hexdigest()
    p = sha256_b64(USER, l.lower())
    resp = sha256url(p, nonce)
    enckey = esc(b64(os.urandom(16)))
    enciv  = esc(b64(os.urandom(16)))
    v = (f"userhash={sha256url(USER, nonce)}"
         f"&RandomKeyhash={sha256url(rkey, nonce)}"
         f"&response={resp}"
         f"&nonce={esc(nonce)}"
         f"&enckey={enckey}&enciv={enciv}")
    st, rb = req("login_web_app.cgi", v,
                 {"Content-Type": "application/x-www-form-urlencoded"})
    j = json.loads(rb)
    if j.get("result") != 0:
        sys.exit(f"login failed: result={j.get('result')} (0=ok, -1/-2=bad creds)")
    TOKEN["v"] = j.get("token")
    return j

# read-only GETs used by the stock UI (from main.js), incl. query strings;
# deliberately excludes *_web_app.cgi actions (WPS, tests, setters)
STATUS_ENDPOINTS = [
    "access_control_status_web_app.cgi", "apn_config_status_web_app.cgi",
    "bluetooth_status_web_app.cgi", "cell_management_get_web_app.cgi",
    "dashboard_device_info_status_web_app.cgi",
    "dashboard_device_status_web_app.cgi",
    "dashboard_ntwtopo_status_web_app.cgi", "dashboard_status_web_app.cgi",
    "ddns_status_web_app.cgi", "device_info_get_web_app.cgi",
    "device_name_status_web_app.cgi", "device_status_web_app.cgi",
    "diag_status_web_app.cgi", "dns_status_web_app.cgi",
    "dongle_status_web_app.cgi", "dongle_status_web_app.cgi?status",
    "esim_status_web_app.cgi", "fastmile_radio_status_web_app.cgi",
    "fastmile_statistics_status_web_app.cgi",
    "firewall_status_web_app.cgi?fire", "ipfilter_status_web_app.cgi",
    "lan_ipv4_status_web_app.cgi", "lan_ipv6_status_web_app.cgi",
    "lan_status_web_app.cgi?lan", "lan_status_web_app.cgi?wlan",
    "led_management_status_web_app.cgi", "log_status_web_app.cgi?info",
    "loidconfig_status_web_app.cgi", "macfilter_status_web_app.cgi",
    "mesh_status_web_app.cgi", "nat_glb_status_web_app.cgi?v=alg",
    "nat_glb_status_web_app.cgi?v=thost", "nat_glb_status_web_app.cgi?v=vhost",
    "overview_get_web_app.cgi", "parental_control_status_web_app.cgi",
    "password_status_web_app.cgi", "pon_status_web_app.cgi",
    "qos_status_web_app.cgi", "radio_config_status_web_app.cgi",
    "route_status_web_app.cgi", "show_wan_status_web_app.cgi?ipv4",
    "show_wan_status_web_app.cgi?ipv6", "slidconfig_status_web_app.cgi",
    "sntp_status_web_app.cgi", "speed_test_status_web_app.cgi?currentSpeed",
    "speed_test_status_web_app.cgi?finalSpeed", "staticroute_get_web_app.cgi",
    "statistics_status_web_app.cgi", "status_get_web_app.cgi",
    "storage_status_web_app.cgi", "tr69_status_web_app.cgi",
    "traffic_control_status_web_app.cgi", "troubleshooting_status_web_app.cgi",
    "uplink_management_status_web_app.cgi", "urlfilter_status_web_app.cgi",
    "voice_setting_status_web_app.cgi?v=cfg_line",
    "volte_info_status_web_app.cgi", "wan_config_glb_status_web_app.cgi",
    "wan_dhcp_status_web_app.cgi", "wan_internet_status_web_app.cgi",
    "whw_beacon_mode_app_status_web_app.cgi?getWorkMode",
    "wifi_schedule_status_web_app.cgi", "wlan_config_status_web_app.cgi",
    "wlan_config_status_web_app.cgi?v=11ac", "xlink_status_web_app.cgi"
]

def do_snapshot():
    """Read-only dump of every status CGI the web UI reads. Human-readable
    record only -- NOT restorable (see the module docstring)."""
    login()
    ts = time.strftime("%Y%m%d-%H%M%S")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                       "snapshots", ts)
    out = os.path.normpath(out)
    os.makedirs(out, exist_ok=True)
    idx = {}
    for ep in STATUS_ENDPOINTS:
        name = re.sub(r"_web_app\.cgi\??", "", ep).replace("=", "-")
        try:
            st, body = req(ep)
            open(f"{out}/{name}.json", "w").write(body)
            idx[name] = {"status": st, "bytes": len(body)}
            print(f"  {st}  {ep}  ({len(body)}B)")
        except Exception as e:
            idx[name] = {"error": str(e)}
            print(f"  ERR {ep}: {e}")
    ok = sum(1 for v in idx.values() if v.get("status") == 200)
    json.dump(idx, open(f"{out}/_index.json", "w"), indent=2)
    print(f"\n{ok}/{len(idx)} pages captured. Snapshot written to: {out}")
    print("(settings record only -- not a restorable backup)")

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "snapshot"
    if cmd in ("snapshot", "backup"):   # `backup` kept as an alias
        if cmd == "backup":
            print("note: 'backup' is a settings SNAPSHOT, not restorable; "
                  "see client/fmbackup.py\n")
        do_snapshot()
    elif cmd == "get":
        login(); print(req(sys.argv[2])[1])
    elif cmd == "post":
        login()
        body = sys.argv[3] if len(sys.argv) > 3 else ""
        body = (body + "&" if body else "") + "csrf_token=" + (TOKEN["v"] or "")
        print(req(sys.argv[2], body,
                  {"Content-Type": "application/x-www-form-urlencoded"})[1])
