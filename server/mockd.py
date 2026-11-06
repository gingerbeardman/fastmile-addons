#!/usr/bin/env python3
"""Mock FastMile gateway web backend for local UI development.

Emulates just enough of the device's CGI surface to develop and test:
  - the login challenge-response (login_web_app.cgi ?nonce / POST)
  - session cookie + csrf token + check_expire
  - a NEW UCI-backed DDNS shim (ddns_uci_web_app.cgi) that we will also
    deploy to the real device; here it is backed by server/ddns_state.json
  - a catch-all for other *_web_app.cgi so the Angular app doesn't hard-fail

Serves the router's own UI bundle from webui-dev/web_whw/ (not part of this
project: copy it from your gateway, see docs/development.md) at /web_whw/,
with device/www/ overlaid on top, so what you test is what deploys.

Run:  python3 -I server/mockd.py          # listens on http://127.0.0.1:8080
Test password defaults to 'testpass' (override with MOCK_PW).
"""
import os, sys, json, hashlib, base64, secrets, posixpath, urllib.parse as UP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBDIR  = os.path.join(ROOT, "webui-dev")
DEVWWW  = os.path.join(ROOT, "device", "www")   # our additions -> /web_whw/
STATE   = os.path.join(ROOT, "server", "ddns_state.json")
USER    = os.environ.get("MOCK_USER", "admin")
PW      = os.environ.get("MOCK_PW", "testpass")
PORT    = int(os.environ.get("MOCK_PORT", "8080"))

# A real (throwaway) 1024-bit public key so crypto_page.encrypt still "works"
# client-side; the login path does not actually need it.
DUMMY_PUBKEY = ("-----BEGIN PUBLIC KEY-----"
  "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQD6eVg/jAg1Swodah2alnMcz9T6ox0"
  "bQCAhGzed7i35c2roHmcFLzQuKEVdyjj1eXaj4Pxp203uG2/IlZSdoU2i9vG3AinNxH"
  "RcJUuEu6mecC1ML2k60GF6jRIUgrEL4fITIbj8m9pmm9WJPwWmeW6NiXI9ilESnNN/Y"
  "jjjs7CIawIDAQAB-----END PUBLIC KEY-----")

import time as _time
SESS_FILE = os.path.join(ROOT, "server", "sessions.json")
TTL = int(os.environ.get("MOCK_TTL", "900"))   # session lifetime, seconds (15 min)
# sid -> {"token":..., "exp":epoch}; persisted so dev restarts don't log you out
try:    SESSIONS = json.load(open(SESS_FILE))
except Exception: SESSIONS = {}
def _save_sessions():
    try: json.dump(SESSIONS, open(SESS_FILE, "w"))
    except Exception: pass

def b64(b):   return base64.b64encode(b).decode()
def esc(s):   return s.replace("+", "-").replace("/", "_").replace("=", ".")
def sha256_b64(a, b): return b64(hashlib.sha256(f"{a}:{b}".encode()).digest())
def sha256url(a, b):  return esc(sha256_b64(a, b))

def default_ddns():
    return {"enabled": "0", "service_name": "changeip.com", "domain": "",
            "username": "", "password": "", "interface": "wan",
            "status": "Not configured"}

def load_ddns():
    try:    return {**default_ddns(), **json.load(open(STATE))}
    except Exception: return default_ddns()

def save_ddns(d):
    json.dump(d, open(STATE, "w"), indent=2)


AGVPN = {"result": 0,
    "status": {"enabled": True, "mode": "cli", "state": "connected", "location": "London",
               "connected_location": "LONDON", "scope": "devices", "devices": "192.168.1.50",
               "tun_ip": "172.16.0.2", "since": 0, "error": ""},
    "locations": {"cli": [{"id": c, "iso": i, "country": n, "city": c, "ping": p} for c, i, n, p in [
        ("London", "GB", "United Kingdom", 4), ("Amsterdam", "NL", "Netherlands", 12),
        ("Paris", "FR", "France", 12), ("Frankfurt", "DE", "Germany", 16),
        ("Manchester", "GB", "United Kingdom", 17), ("Dublin", "IE", "Ireland", 18),
        ("New York", "US", "United States", 91), ("Los Angeles", "US", "United States", 162)]],
                  "ipsec": [{"id": c, "iso": c.upper(), "country": n, "city": t, "ping": 0} for c, t, n in [
        ("gb", "London", "United Kingdom"), ("de", "Frankfurt", "Germany"), ("nl", "Amsterdam", "Netherlands"),
        ("fi", "Helsinki", "Finland"), ("us", "New York", "United States")]]},
    "devices": [{"ip": "192.168.1.50", "mac": "02:00:00:00:00:01", "name": "Laptop", "type": "802.11ac"},
                {"ip": "192.168.1.51", "mac": "02:00:00:00:00:02", "name": "Unknown_02", "type": "802.11ac"},
                {"ip": "192.168.1.52", "mac": "02:00:00:00:00:03", "name": "Printer", "type": "802.11"},
                {"ip": "192.168.1.53", "mac": "02:00:00:00:00:04", "name": "Clock", "type": "802.11"}]}


class H(BaseHTTPRequestHandler):
    server_version = "mock-fastmile/0.1"

    # ---- helpers ----
    def _send(self, code, body=b"", ctype="application/json", extra=None):
        if isinstance(body, str): body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store,max-age=0")
        for k, v in (extra or {}):
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, extra=None):
        self._send(200, json.dumps(obj), "application/json", extra)

    def _cookies(self):
        c = {}
        for part in (self.headers.get("Cookie") or "").split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1); c[k] = v
        return c

    def _sid_valid(self):
        sid = self._cookies().get("sid")
        s = SESSIONS.get(sid)
        if not s: return False
        if _time.time() >= s["exp"]:          # expired
            SESSIONS.pop(sid, None); _save_sessions(); return False
        s["exp"] = _time.time() + TTL          # sliding renewal on activity
        _save_sessions()
        return True

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n).decode("utf-8", "replace") if n else ""

    # ---- routing ----
    def do_HEAD(self): self.do_GET()

    def do_GET(self):
        u = UP.urlparse(self.path)
        path, qs = u.path, UP.parse_qs(u.query, keep_blank_values=True)

        if path == "/login_web_app.cgi" and "nonce" in qs:
            self._nonce = secrets.token_bytes(32)
            n = b64(self._nonce)
            # stash nonce in a cookie so POST can verify statelessly
            return self._json(
                {"nonce": n, "randomKey": "481", "iterations": 1,
                 "pubkey": DUMMY_PUBKEY},
                extra=[("Set-Cookie", f"lnonce={esc(n)}; Path=/")])

        if path == "/check_expire_web_app.cgi":
            return self._json({"expired": "no" if self._sid_valid() else "yes"})

        if path == "/_devseed":   # dev only: seed stored credential for headless
            to = (qs.get("to") or [""])[0]       # optional target
            if to.endswith(".html"): dest = "/web_whw/" + to
            elif to:                 dest = "/web_whw/#/" + to
            else:                    dest = "/web_whw/"
            html = ("<!doctype html><meta charset=utf-8><script>"
                    "localStorage.setItem('fm_pw','%s');"
                    "location.replace('%s');</script>seeding" % (PW, dest))
            return self._send(200, html, "text/html")

        if path == "/ddns_uci_web_app.cgi":        # our shim: read
            if not self._sid_valid(): return self._send(403, '{"result":-1}')
            d = load_ddns(); d = {**d, "password": ""}   # never leak pw to client
            return self._json(d)

        if path == "/agvpn_web_app.cgi":           # our VPN CGI: read
            if not self._sid_valid(): return self._send(401, '{"result":-401,"reason":"login required"}')
            return self._json(AGVPN)

        # catch-all for other status CGIs so data-gated UI still renders
        if path.endswith("_web_app.cgi"):
            return self._json({"result": 0})

        # static files
        if path == "/" or path == "/web_whw" :
            return self._redirect("/web_whw/")
        return self._static(path)

    def do_POST(self):
        u = UP.urlparse(self.path)
        path, qs = u.path, UP.parse_qs(u.query, keep_blank_values=True)
        form = UP.parse_qs(self._body())

        if path == "/login_web_app.cgi" and "out" in qs:
            SESSIONS.pop(self._cookies().get("sid", ""), None); _save_sessions()
            return self._json({"result": 0})

        if path == "/login_web_app.cgi":
            nonce_b64 = self._cookies().get("lnonce", "").replace("-", "+")\
                        .replace("_", "/").replace(".", "=")
            got_resp  = (form.get("response") or [""])[0]
            got_uhash = (form.get("userhash") or [""])[0]
            # recompute expected using the same nonce we issued
            l = hashlib.sha256(PW.encode()).hexdigest()
            p = sha256_b64(USER, l.lower())
            exp_resp  = sha256url(p, nonce_b64)
            exp_uhash = sha256url(USER, nonce_b64)
            if got_resp == exp_resp and got_uhash == exp_uhash:
                sid = secrets.token_hex(16); tok = secrets.token_hex(16)
                SESSIONS[sid] = {"token": tok, "exp": _time.time() + TTL}
                _save_sessions()
                return self._json(
                    {"result": 0, "sid": sid, "token": tok},
                    extra=[("Set-Cookie", f"sid={sid}; Path=/; HttpOnly")])
            return self._json({"result": -1})

        if path == "/ddns_uci_web_app.cgi":        # our shim: write
            if not self._sid_valid(): return self._send(403, '{"result":-1}')
            _s = SESSIONS.get(self._cookies().get("sid")); tok = _s and _s["token"]
            if (form.get("csrf_token") or [""])[0] != tok:
                return self._json({"result": -3, "reason": "bad csrf"})
            cur = load_ddns()
            for k in ("enabled", "service_name", "domain", "username",
                      "interface"):
                if k in form: cur[k] = form[k][0]
            if form.get("password", [""])[0]:      # only update if provided
                cur["password"] = form["password"][0]
            cur["status"] = ("Enabled, update pending" if cur["enabled"] == "1"
                             else "Disabled")
            save_ddns(cur)
            return self._json({"result": 0, "status": cur["status"]})

        if path == "/agvpn_web_app.cgi":           # our VPN CGI: write
            if not self._sid_valid(): return self._send(401, '{"result":-401,"reason":"login required"}')
            if not (form.get("csrf_token") or [""])[0]:
                return self._json({"result": -1, "reason": "missing csrf"})
            st = AGVPN["status"]
            if "enabled" in form: st["enabled"] = form["enabled"][0] == "1"
            for k in ("mode", "location", "scope"):
                if k in form: st[k] = form[k][0]
            if "devices" in form: st["devices"] = " ".join(x for x in form["devices"][0].split(",") if x)
            st["state"] = "connected" if st["enabled"] else "off"
            st["connected_location"] = st["location"].upper() if st["enabled"] else ""
            return self._json({"result": 0, "status": st})

        # catch-all: pretend-OK so the Angular app keeps going
        if path.endswith("_web_app.cgi"):
            return self._json({"result": 0})
        self._send(404, '{"result":-1}')

    # ---- static ----
    def _redirect(self, to):
        self._send(302, b"", "text/plain", [("Location", to)])

    def _static(self, path):
        rel = path.lstrip("/")
        # overlay our additions (device/www) onto /web_whw/ so dev == deploy
        if path.startswith("/web_whw/"):
            sub = path[len("/web_whw/"):]
            if sub == "" or sub.endswith("/"):
                sub += "index.html"          # directory -> our patched index
            cand = os.path.normpath(os.path.join(DEVWWW, sub))
            if cand.startswith(DEVWWW) and os.path.isfile(cand):
                return self._serve_file(cand)
        fp = os.path.normpath(os.path.join(WEBDIR, rel))
        if not fp.startswith(WEBDIR):          # path traversal guard
            return self._send(403, b"forbidden", "text/plain")
        if os.path.isdir(fp): fp = os.path.join(fp, "index.html")
        if not os.path.isfile(fp):
            # Angular SPA fallback for /web_whw/* deep links
            if path.startswith("/web_whw/"):
                fp = os.path.join(WEBDIR, "web_whw", "index.html")
            else:
                return self._send(404, b"not found", "text/plain")
        self._serve_file(fp)

    def _serve_file(self, fp):
        ctype = {
            ".html":"text/html", ".js":"application/javascript",
            ".css":"text/css", ".json":"application/json", ".svg":"image/svg+xml",
            ".png":"image/png", ".ico":"image/x-icon", ".woff2":"font/woff2",
            ".woff":"font/woff", ".ttf":"font/ttf", ".eot":"application/vnd.ms-fontobject",
        }.get(os.path.splitext(fp)[1], "application/octet-stream")
        with open(fp, "rb") as f: data = f.read()
        self._send(200, data, ctype)

    def log_message(self, fmt, *a):
        sys.stderr.write("  %s - %s\n" % (self.address_string(), fmt % a))


if __name__ == "__main__":
    if not os.path.isfile(os.path.join(WEBDIR, "web_whw", "index.html")):
        print("warning: webui-dev/web_whw/index.html missing; copy the router's "
              "web UI there first (docs/development.md)", file=sys.stderr)
    if not os.path.exists(STATE): save_ddns(default_ddns())
    print(f"mock gateway on http://127.0.0.1:{PORT}  (user={USER} pw={PW!r})")
    print(f"  UI:        http://127.0.0.1:{PORT}/web_whw/")
    print(f"  DDNS page: http://127.0.0.1:{PORT}/web_whw/ddns.html")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
