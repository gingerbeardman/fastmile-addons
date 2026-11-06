#!/usr/bin/python3
# <xbar.title>AdGuard VPN (FastMile)</xbar.title>
# <xbar.version>1.0</xbar.version>
# <xbar.author>Matt Sephton</xbar.author>
# <xbar.author.github>gingerbeardman</xbar.author.github>
# <xbar.desc>Control the AdGuard VPN on a Nokia FastMile 5G router.</xbar.desc>
# <xbar.dependencies>python3</xbar.dependencies>
# <swiftbar.hideAbout>true</swiftbar.hideAbout>
# <swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
"""AdGuard VPN menu-bar plugin for xbar / SwiftBar.

Talks to http://192.168.1.1/agvpn_web_app.cgi using the router's normal web
session (sid cookie + csrf token). Self-contained, stdlib only.

  agvpn.30s.py                       render the menu
  agvpn.30s.py connect|disconnect
  agvpn.30s.py location <id>         (id may be %-encoded)
  agvpn.30s.py mode cli|ipsec
  agvpn.30s.py device <ip>           toggle one device in the VPN list
  agvpn.30s.py open                  open the router's VPN page
  agvpn.30s.py sort ping|alpha       how the Location menu is ordered (saved locally)
  agvpn.30s.py region                toggle the region in the menu-bar title (until logout)
  agvpn.30s.py login                 log in to the router (ends the browser's session)

Env: FM_HOST (default http://192.168.1.1), FM_USER (default superadmin),
FM_PASS (overrides the Keychain item "fastmile-router"),
AGVPN_DRY_RUN=1 (print the POST body instead of sending it).
"""
import base64
import hashlib
import http.cookiejar
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HOST = os.environ.get("FM_HOST", "http://192.168.1.1").rstrip("/")
USER = os.environ.get("FM_USER", "superadmin")
CGI = "agvpn_web_app.cgi"
VPN_PAGE = HOST + "/web_whw/vpn.html"
KEYCHAIN_SERVICE = "fastmile-router"
CACHE = os.path.expanduser("~/Library/Caches/fastmile-agvpn/session.json")
PREFS = os.path.expanduser("~/Library/Application Support/fastmile-agvpn/prefs.json")
SORTS = (("ping", "Ping (fastest first)"), ("alpha", "Alphabetical (by country)"))
# "Show region in menu bar" is deliberately not saved: the flag lives in the
# per-login temp dir, so it lasts until logout or restart. Default off.
REGION_FLAG = os.path.join(os.environ.get("TMPDIR") or "/tmp",
                           "fastmile-agvpn-%d-show-region" % os.getuid())


def show_region():
    return os.path.exists(REGION_FLAG)


def load_prefs():
    try:
        with open(PREFS) as f:
            p = json.load(f)
    except (OSError, ValueError):
        p = {}
    if p.get("sort") not in dict(SORTS):
        p["sort"] = "ping"
    return p


def save_prefs(p):
    os.makedirs(os.path.dirname(PREFS), exist_ok=True)
    tmp = PREFS + ".tmp"
    with open(tmp, "w") as f:
        json.dump(p, f)
    os.replace(tmp, PREFS)
TIMEOUT = 4
DRY_RUN = os.environ.get("AGVPN_DRY_RUN") == "1"
SWIFTBAR = os.environ.get("SWIFTBAR") == "1"
SELF = os.path.realpath(sys.argv[0])


class AuthError(Exception):
    pass


class LoginFailed(Exception):
    pass


# ---------------------------------------------------------------- login ----
# Port of client/fm.py login(): the web_whw sjcl challenge-response.

def _b64(b):
    return base64.b64encode(b).decode()


def _esc(s):
    return s.replace("+", "-").replace("/", "_").replace("=", ".")


def _sha256_b64(a, b):
    return _b64(hashlib.sha256(("%s:%s" % (a, b)).encode()).digest())


def _sha256url(a, b):
    return _esc(_sha256_b64(a, b))


def get_password():
    pw = os.environ.get("FM_PASS")
    if pw:
        return pw
    try:
        out = subprocess.run(
            ["/usr/bin/security", "find-generic-password",
             "-s", KEYCHAIN_SERVICE, "-a", USER, "-w"],
            capture_output=True, text=True, timeout=10)
    except Exception:
        out = None
    if not out or out.returncode != 0 or not out.stdout.strip():
        raise LoginFailed("no Keychain item '%s' for %s" % (KEYCHAIN_SERVICE, USER))
    return out.stdout.rstrip("\n")


def login():
    pw = get_password()
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    with opener.open(HOST + "/login_web_app.cgi?nonce", timeout=TIMEOUT) as r:
        n = json.loads(r.read().decode("utf-8", "replace"))
    nonce, rkey = n["nonce"], n["randomKey"]
    iters = int(n.get("iterations", 1))
    h = hashlib.sha256(pw.encode()).hexdigest() if iters >= 1 else pw
    for _ in range(1, iters):
        h = hashlib.sha256(bytes.fromhex(h)).hexdigest()
    resp = _sha256url(_sha256_b64(USER, h.lower()), nonce)
    body = ("userhash=%s&RandomKeyhash=%s&response=%s&nonce=%s&enckey=%s&enciv=%s"
            % (_sha256url(USER, nonce), _sha256url(rkey, nonce), resp,
               _esc(nonce), _esc(_b64(os.urandom(16))), _esc(_b64(os.urandom(16)))))
    req = urllib.request.Request(
        HOST + "/login_web_app.cgi", data=body.encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    with opener.open(req, timeout=TIMEOUT) as r:
        j = json.loads(r.read().decode("utf-8", "replace"))
    if j.get("result") != 0:
        raise LoginFailed("login failed (result %s)" % j.get("result"))
    cookies = {c.name: c.value for c in cj}
    if "sid" not in cookies:
        raise LoginFailed("login returned no sid cookie")
    sess = {"cookies": cookies, "token": j.get("token") or "", "time": int(time.time())}
    save_session(sess)
    return sess


def load_session():
    try:
        with open(CACHE) as f:
            s = json.load(f)
        if s.get("cookies", {}).get("sid"):
            return s
    except Exception:
        pass
    return None


def save_session(sess):
    d = os.path.dirname(CACHE)
    os.makedirs(d, mode=0o700, exist_ok=True)
    tmp = CACHE + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(sess, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, CACHE)


def clear_session():
    try:
        os.remove(CACHE)
    except OSError:
        pass


# ------------------------------------------------------------------ api ----

TOKEN_SERVICE = "fastmile-agvpn-token"


def get_api_token():
    """Token for the CGI's X-AGVPN-Token header (env AGVPN_TOKEN or Keychain).
    With a token the plugin never logs in, so it can't end the browser's
    session: the router allows only one web session at a time."""
    t = os.environ.get("AGVPN_TOKEN")
    if t:
        return t
    try:
        out = subprocess.run(["/usr/bin/security", "find-generic-password",
                              "-s", TOKEN_SERVICE, "-a", "router", "-w"],
                             capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return None


def _call(sess, data=None):
    if sess.get("api_token"):
        headers = {"X-AGVPN-Token": sess["api_token"]}
    else:
        headers = {"Cookie": "; ".join("%s=%s" % kv for kv in sess["cookies"].items())}
    body = None
    if data is not None and not sess.get("api_token"):
        data = dict(data, csrf_token=sess["token"])
    if data is not None:
        body = urllib.parse.urlencode(data).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(HOST + "/" + CGI, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise AuthError()
        raw = e.read()
        try:
            j = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            raise RuntimeError("HTTP %d" % e.code)
        if j.get("result") == -401:
            raise AuthError()
        raise RuntimeError(j.get("reason") or "HTTP %d" % e.code)
    j = json.loads(raw.decode("utf-8", "replace"))
    if j.get("result") == -401:
        raise AuthError()
    return j


class SessionEnded(Exception):
    pass


def api(data=None, allow_login=False):
    """GET (data=None) or POST.

    With an API token: token only, never a login. Without one: reuse the cached
    session, but don't log in again on a 401 unless asked (allow_login), because
    a new login would end the session in the user's browser."""
    tok = get_api_token()
    if tok:
        try:
            return _call({"api_token": tok}, data)
        except AuthError:
            raise LoginFailed("API token rejected by the router")
    sess = load_session()
    if not sess:
        if not allow_login:
            raise SessionEnded()
        sess = login()
    try:
        return _call(sess, data)
    except AuthError:
        clear_session()
        if not allow_login:
            raise SessionEnded()
        return _call(login(), data)


def get_state():
    return api()


def post(fields):
    if DRY_RUN:
        shown = dict(fields, csrf_token="<token>")
        print("POST %s/%s\n%s" % (HOST, CGI, urllib.parse.urlencode(shown)))
        return {"result": 0, "dry_run": True}
    return api(fields)


# -------------------------------------------------------------- actions ----

def notify(msg):
    if DRY_RUN:
        print("notify:", msg)
        return
    s = msg.replace("\\", "\\\\").replace('"', '\\"')
    subprocess.run(["/usr/bin/osascript", "-e",
                    'display notification "%s" with title "AdGuard VPN"' % s],
                   capture_output=True)


def wait_for(pred, timeout=15):
    if DRY_RUN:
        return True
    end = time.time() + timeout
    time.sleep(2)
    while True:
        try:
            if pred(get_state().get("status", {})):
                return True
        except Exception:
            pass
        if time.time() > end:
            return False
        time.sleep(1.5)


def pick_location(locs, iso, current=None):
    """Location id in `locs` for country `iso`, preferring the current id."""
    ids = [l["id"] for l in locs]
    if current in ids:
        return current
    for l in locs:  # lists are sorted by ping, so this is the fastest match
        if l.get("iso") == iso:
            return l["id"]
    return ids[0] if ids else None


def connected_loc(data):
    """The location entry in use: the chosen one, or for "fastest" the one the
    router reports it connected to (connected_location is e.g. LONDON or
    "LONDON (gb)")."""
    st = data.get("status", {})
    locs = data.get("locations", {}).get(st.get("mode"), [])
    for l in locs:
        if l["id"] == st.get("location"):
            return l
    got = (st.get("connected_location") or "").split(" (")[0].strip().lower()
    for l in locs:
        if got and (l.get("city") or "").lower() == got:
            return l
    return None


def current_iso(data):
    l = connected_loc(data)
    return l.get("iso", "") if l else ""


def run_action(args):
    act = args[0]
    if act == "open":
        subprocess.run(["/usr/bin/open", VPN_PAGE])
        return 0
    if act == "refresh":
        return 0
    if act == "login":   # explicit: this ends the browser's router session
        api(allow_login=True)
        request_refresh()
        return 0
    if act == "region":
        if show_region():
            os.remove(REGION_FLAG)
        else:
            open(REGION_FLAG, "w").close()
        request_refresh()
        return 0
    if act == "sort" and len(args) > 1 and args[1] in dict(SORTS):
        p = load_prefs(); p["sort"] = args[1]; save_prefs(p)
        request_refresh()
        return 0
    data = get_state()
    st = data.get("status", {})

    if act == "connect":
        fields = {"action": "apply", "enabled": "1"}
        pred = lambda s: s.get("state") in ("connected", "fallback", "error")
    elif act == "disconnect":
        fields = {"action": "apply", "enabled": "0"}
        pred = lambda s: s.get("state") == "off"
    elif act == "location" and len(args) > 1:
        loc = urllib.parse.unquote(args[1])
        fields = {"action": "apply", "enabled": "1", "location": loc}
        pred = lambda s: s.get("location") == loc and s.get("state") == "connected"
    elif act == "mode" and len(args) > 1 and args[1] in ("cli", "ipsec"):
        mode = args[1]
        if mode == st.get("mode"):
            return 0
        fields = {"action": "apply", "mode": mode}
        loc = pick_location(data.get("locations", {}).get(mode, []), current_iso(data))
        if loc:
            fields["location"] = loc
        pred = lambda s: s.get("mode") == mode and s.get("state") != "connecting"
    elif act == "device" and len(args) > 1:
        ip = args[1]
        cur = [d for d in (st.get("devices") or "").replace(" ", "").split(",") if d]
        new = [d for d in cur if d != ip] if ip in cur else cur + [ip]
        if not new:
            notify("At least one device must stay on the VPN")
            return 1
        devs = ",".join(new)
        fields = {"action": "apply", "scope": "devices", "devices": devs}
        pred = lambda s: (s.get("devices") or "").replace(" ", "") == devs
    else:
        sys.stderr.write(__doc__)
        return 2

    r = post(fields)
    if r.get("result") != 0:
        notify("Failed: %s" % (r.get("reason") or r.get("result")))
        return 1
    if not wait_for(pred):
        notify("Change sent; router has not confirmed it yet")
    request_refresh()
    return 0


def request_refresh():
    """xbar runs actions asynchronously and redraws immediately, before the
    router has reconnected, so ask for another redraw once the change is done."""
    if DRY_RUN:
        return
    name = os.path.basename(SELF)
    url = ("swiftbar://refreshplugin?name=%s" % name.split(".")[0] if SWIFTBAR
           else "xbar://app.xbarapp.com/refreshPlugin?path=%s" % urllib.parse.quote(name))
    subprocess.run(["/usr/bin/open", "-g", url], capture_output=True)


# ----------------------------------------------------------------- menu ----

def clean(s):
    return str(s).replace("|", "¦").replace("\n", " ")


def dev_name(d):
    """Router hostnames like Unknown_02:00:00:00:00:01 read badly; say so plainly."""
    n = (d.get("name") or "").strip()
    if n and not n.lower().startswith("unknown"):
        return n
    mac = (d.get("mac") or "").lower()
    return "Unknown device (…%s)" % mac[-8:] if len(mac) >= 8 else "Unknown device"


def item(text, action=None, *params, **opts):
    line = clean(text)
    attrs = []
    if action:
        attrs.append('bash="%s"' % SELF)
        for i, p in enumerate((action,) + params, 1):
            attrs.append("param%d=%s" % (i, urllib.parse.quote(str(p), safe="")))
        attrs += ["terminal=false", "refresh=true"]
    attrs.append("emojize=false")
    for k, v in opts.items():
        attrs.append("%s=%s" % (k, v))
    return line + (" | " + " ".join(attrs) if attrs else "")


ON, OFF = "\u26ca", "\u26c9"   # ⛊ turned black shogi piece = on, ⛉ turned white = off


def title(text, sf=None, emoji_text=None):
    """Menu-bar title. Plain text in both xbar and SwiftBar; emoji conversion off."""
    return "%s | emojize=false" % text


def ago(since):
    try:
        s = int(time.time()) - int(since)
    except (TypeError, ValueError):
        return ""
    if s < 0 or not since:
        return ""
    if s < 3600:
        return "%dm" % (s // 60)
    if s < 86400:
        return "%dh %dm" % (s // 3600, s % 3600 // 60)
    return "%dd %dh" % (s // 86400, s % 86400 // 3600)


SLOW_MS = 50   # locations at or above this ping go in the "Slower locations" submenu


def location_menu(locs, cur):
    out = []
    check = lambda l: ("✓ " if l["id"] == cur else "    ")

    def label(l, with_country=True):
        name = l.get("city") or l["id"]
        if with_country and l.get("country") and l.get("country") != name:
            name = "%s, %s" % (name, l["country"])
        ping = l.get("ping")
        return "%s%s%s" % (check(l), name, "  (%d ms)" % ping if ping else "")

    if len(locs) <= 15:
        for l in locs:
            out.append(item("--" + label(l), "location", l["id"]))
        return out

    def by_country(group, depth):
        """Country entries at `depth` dashes; multi-city countries get a submenu."""
        d = "-" * depth
        res, groups = [], {}
        for l in group:
            groups.setdefault(l.get("country") or l["id"], []).append(l)
        for country in sorted(groups):
            g = groups[country]
            if len(g) == 1:
                res.append(item(d + label(g[0]), "location", g[0]["id"]))
            else:
                mark = "✓ " if any(l["id"] == cur for l in g) else "    "
                res.append(item("%s%s%s" % (d, mark, country)))
                for l in g:
                    res.append(item(d + "--" + label(l, False), "location", l["id"]))
        return res

    out.append(item("--%sFastest available" % ("✓ " if cur == "fastest" else "    "),
                    "location", "fastest"))
    out.append("-----")
    def by_ping(group, depth):
        d = "-" * depth
        return [item(d + label(l), "location", l["id"])
                for l in sorted(group, key=lambda l: (l.get("ping") or 0, l.get("city") or l["id"]))]

    listing = by_ping if load_prefs()["sort"] == "ping" else by_country
    near = [l for l in locs if (l.get("ping") or 0) < SLOW_MS]
    far = [l for l in locs if (l.get("ping") or 0) >= SLOW_MS]
    out += listing(near, 2)
    if far:
        out.append("-----")
        mark = "✓ " if any(l["id"] == cur for l in far) else "    "
        out.append(item("--%sSlower locations (%d ms+)" % (mark, SLOW_MS)))
        out += listing(far, 4)
    return out


def render():
    try:
        data = get_state()
    except SessionEnded:
        print(title(OFF + " ?"))
        print("---")
        print(item("Router session ended", color="#888888"))
        print(item("The router allows one login at a time, so the plugin won't log in by itself.", size=11))
        print(item("Log in now (logs the browser out)", "login"))
        print(item("Set up an API token to avoid this: see README.md", size=11))
        print("---")
        print(item("Open VPN page", "open"))
        print(item("Refresh", "refresh"))
        return
    except LoginFailed as e:
        print(title(OFF + " ?"))
        print("---")
        print(item("Login failed: %s" % e))
        print(item("Set the password: see README.md"))
        print(item("Refresh", "refresh"))
        return
    except Exception as e:
        print(title(OFF + " ?"))
        print("---")
        print(item("Router unreachable (%s)" % (getattr(e, "reason", None) or e)))
        print(item("Open VPN page", "open"))
        print(item("Refresh", "refresh"))
        return

    st = data.get("status", {})
    state = st.get("state", "off")
    mode = st.get("mode", "cli")
    locs = data.get("locations", {}).get(mode, [])
    iso = current_iso(data)
    cur_loc = connected_loc(data)

    if state == "connected":
        print(title("%s %s" % (ON, iso) if iso and show_region() else ON))
    elif state == "connecting":
        print(title(ON + " …"))
    elif state in ("fallback", "error"):
        print(title(OFF + " !"))
    else:
        print(title(OFF))
    print("---")

    where = st.get("connected_location") or st.get("location") or ""
    if cur_loc:
        where = "%s, %s" % (cur_loc.get("city") or cur_loc["id"], cur_loc.get("country", ""))
    label = {"off": "Off", "connecting": "Connecting", "connected": "Connected",
             "fallback": "Fallback (tunnel down, normal connection)",
             "error": "Error"}.get(state, state)
    print(item("%s%s" % (label, " · " + where if state != "off" and where else "")))
    details = ["Mode: %s" % ("IPsec" if mode == "ipsec" else "CLI")]
    if st.get("tun_ip") and state != "off":
        details.append("Tunnel %s" % st["tun_ip"])
    if state == "connected" and ago(st.get("since")):
        details.append("up %s" % ago(st.get("since")))
    print(item(" · ".join(details), size=12))
    if st.get("error"):
        print(item("Error: %s" % st["error"], color="#cc3333", size=12))
    print("---")

    if st.get("enabled") or state != "off":
        print(item("Disconnect", "disconnect"))
    else:
        print(item("Connect", "connect"))

    city = cur_loc.get("city") if cur_loc else ""
    if st.get("location") == "fastest":
        loc_label = "Fastest" + (" (%s)" % city if city else "")
    else:
        loc_label = city or st.get("location") or "—"
    print(item("Location: %s" % loc_label))
    for line in location_menu(locs, st.get("location")):
        print(line)
    if len(locs) > 15:
        sort = load_prefs()["sort"]
        print("-----")
        print(item("--Sort by"))
        for key, name in SORTS:
            print(item("----%s%s" % ("✓ " if key == sort else "    ", name), "sort", key))

    print("Mode")
    for m, name in (("cli", "CLI (%d locations)" % len(data.get("locations", {}).get("cli", []))),
                    ("ipsec", "IPsec (%d servers)" % len(data.get("locations", {}).get("ipsec", [])))):
        print(item("--%s%s" % ("✓ " if m == mode else "    ", name), "mode", m))

    scope = st.get("scope", "all")
    vpn_ips = [d for d in (st.get("devices") or "").replace(" ", "").split(",") if d]
    devices = data.get("devices", [])
    if scope == "all":
        print("Devices: all")
        print("--All devices use the VPN")
        print("-----")
        for d in devices:
            print(item("--%s  %s" % (dev_name(d), d.get("ip")), size=12))
    else:
        print("Devices: %d" % len(vpn_ips))
        known = {d.get("ip"): d for d in devices}
        for ip in vpn_ips:
            d = known.get(ip, {})
            name = dev_name(d) if d else "(offline)"
            print(item("--✓ %s  %s" % (name, ip), "device", ip))
        others = [d for d in devices if d.get("ip") not in vpn_ips]
        if others:
            print("-----")
            print("--Not on VPN (click to add) | size=11")
            for d in others:
                print(item("--    %s  %s" % (dev_name(d), d.get("ip")),
                           "device", d.get("ip")))
    print("---")
    print(item("%sShow region in menu bar" % ("✓ " if show_region() else ""), "region"))
    print(item("Open VPN page", "open"))
    print(item("Refresh", "refresh"))


def main():
    if len(sys.argv) > 1:
        try:
            return run_action(sys.argv[1:])
        except SessionEnded:
            notify("Router session ended. Use “Log in now” in the menu, or set up an API token.")
            return 1
        except Exception as e:
            notify("Error: %s" % (getattr(e, "reason", None) or e))
            return 1
    render()
    return 0


if __name__ == "__main__":
    sys.exit(main())
