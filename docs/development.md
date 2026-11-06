# Development

The pages and the login code can be developed on a computer against a mock
gateway, without touching the router.

## Get a copy of the router's web UI

The mock serves the router's own Angular bundle, which isn't part of this
project. Copy it from your gateway into `webui-dev/web_whw/` (git-ignored),
for example:

```sh
wget -r -np -nH -P webui-dev http://192.168.1.1/web_whw/
```

Any method that gets the static files works (index.html, `main.*.js`,
`runtime.*.js`, `polyfills.*.js`, `styles.*.css`, `assets/`). The harness
needs `assets/js/jsencrypt.min.js`, `sjcl.js` and `crypto_page.js`.

Then patch the local index the same way the router's is patched:

```sh
sh device/patch-index.sh webui-dev/web_whw/index.html
```

## Mock gateway

```sh
MOCK_PW=testpass python3 -I server/mockd.py        # http://127.0.0.1:8080/web_whw/
```

- Serves `webui-dev/` with `device/www/` overlaid onto `/web_whw/`, so what
  you test is what deploys.
- Emulates the login challenge-response (`login_web_app.cgi?nonce` and the
  hashed POST), the session cookie, the csrf token and `check_expire`.
- Emulates `ddns_uci_web_app.cgi` (state in `server/ddns_state.json`) and an
  in-memory `agvpn_web_app.cgi` with sample locations and devices for the VPN
  page. Other `*_web_app.cgi` calls get a harmless catch-all answer.
- Sessions are kept in `server/sessions.json` so restarts don't log you out.

| Variable | Default | Meaning |
|---|---|---|
| `MOCK_PW` | `testpass` | password the mock accepts |
| `MOCK_USER` | `admin` | user name (`superadmin` shows the superadmin-only menu items) |
| `MOCK_PORT` | `8080` | listen port (127.0.0.1 only) |
| `MOCK_TTL` | `900` | session lifetime in seconds; lower it to test auto re-login |

## Headless harness

```sh
MOCK_PW=testpass node server/harness.mjs           # -> ALL CHECKS PASSED
```

Loads the real crypto stack and `device/www/fm-auth.js` into a Node VM and
drives them against the mock: login handshake, csrf token, DDNS read and
write. Needs Node 18 or later (built-in `fetch`). Point it at another host
with `FM_HOST`.

## CLI client

```sh
FM_HOST=http://127.0.0.1:8080 NOKIA=testpass python3 -I client/fm.py get ddns_uci_web_app.cgi
NOKIA=... python3 -I client/fm.py snapshot          # read-only dump from the real router
```

Against the real router, remember that a login ends the browser's session.

## Testing on the router

- Use `update-ui.sh` for page, menu and theme changes: it replaces only the
  web files and keeps every other keeper member.
- Bump the `?v=` numbers when a file changes (see [web-ui.md](web-ui.md)).
- Shell scripts must run under BusyBox ash: no bash, python or perl on the
  device. `sh -n` catches syntax errors before you upload.
- The CGIs can be exercised on the router with
  `REQUEST_METHOD=GET sh /webs/<name>.cgi`; the speed test CGI also has
  `--selftest`.
