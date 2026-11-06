# Web UI add-ons

The stock web UI (`/webs/web_whw/`, an Angular app) is left alone apart from
a small, reversible patch to its `index.html` (`device/patch-index.sh`). Every
addition is a separate file next to it:

| File | What it does |
|---|---|
| `fm-menu.js` | Flat side menu, shared by the stock app and the add-on pages; session keep-alive |
| `fm-theme.css`, `fm-theme.js` | Dark theme that follows the OS, zoom, layout fixes |
| `fm-auth.js` | Login helper (reuses the router's own crypto), auto re-login |
| `ddns.html` | Dynamic DNS page (Application → Dynamic DNS) |
| `adblock.html` | Adblock page (Security → Adblock) |
| `vpn.html` | AdGuard VPN page (Application → VPN), see [vpn.md](vpn.md) |

The CGIs that back the pages live in `/webs/` (`device/cgi/`).

## What patch-index.sh changes

It edits the router's own `/webs/web_whw/index.html` in place and keeps the
stock file as `index.html.orig`. Each run regenerates the patched file from
the `.orig`, so it is safe to run again (for example to pick up new `?v=`
numbers). It:

- adds `fm-theme.css` and `fm-theme.js` before `</head>`
- adds `fm-auth.js` (and the stock crypto scripts, if missing) before
  `<app-root>`, and `fm-menu.js` after it
- replaces the stock `<script type="module">` tags with an **auto-login
  hook**: if a password is stored in the browser, it logs in first, then loads
  the same Angular modules in order. Without one, Angular boots normally and
  shows its own login screen. The module file names are read from the stock
  tags, so other firmware builds work too.

Revert with `cp index.html.orig index.html` (and remove it from the boot
keeper, see below).

## Flat menu

The stock collapsible menu is replaced with one always-expanded list where the
hierarchy is shown only by indentation, in a narrower sidebar.

- Items mirror the stock menu, plus **Dynamic DNS**, **VPN** (Application)
  and **Adblock** (Security). Labels come from the stock i18n files.
- Entries with no page of their own are styled as headings (smaller, grey).
- The three **superadmin-only** stock pages are included, but shown only when
  the logged-in user is superadmin (as in the stock menu):
  Network → Cellular → **Cell Management**, Network → **ACS** (renamed from
  "ACS - Auto Configuration Server") and Security → **Access Control**.
- The menu sits between the logo and the logout bar and scrolls within the
  full sidebar height.
- The language picker is hidden.
- The Overview page's 5G/4G Radio Access panels open once per render; a
  collapse sticks.

## Dark theme and zoom

- `fm-theme.js` toggles `html.fm-dark` from `prefers-color-scheme`, live.
- `fm-theme.css` restyles the stock app and the add-on pages for dark mode
  (status dots, error text, tooltips, logo, the Messages icon, Access Control
  labels and so on). Light mode keeps the stock look.
- `html{zoom:.9}` fits more on screen. Change it in `fm-theme.css`.

## Sessions: keep-alive and auto re-login

The router ends a session after **900 s** without an authenticated request.
`check_expire_web_app.cgi` reports the remaining time but doesn't reset it,
so the stock app's 10 s polling doesn't keep a session alive. The router also
allows **one session at a time**: a new login ends the previous one.

- **Stored login:** `fm-auth.js` keeps the password in the browser's
  `localStorage` (`fm_pw`) and the account in `fm_user` (default `admin`).
  It is never written into a file served by the router. A login on the stock
  screen stores both once the app confirms the user, so a superadmin stays
  superadmin after a re-login. `FM.forget()` (or clearing site data) removes
  them.
- **Keep-alive:** `fm-menu.js`, loaded on every page, checks `check_expire`
  every 4 minutes and on tab focus. While the session is valid it makes one
  authenticated GET, which resets the countdown. It never logs in by itself
  on a timer.
- **Auto re-login:** `fm-auth.js` wraps the stock app's `check_expire` poll.
  If it says "expired" and a password is stored, it logs in again (one at a
  time) and gives the app a fresh answer, so there's no "Session expired"
  dialog after the computer sleeps. Network errors on that poll are ignored,
  since Wi-Fi often takes a few seconds to come back after wake. The
  keep-alive also re-logs in on tab focus.
- **Limits:** the tab has to stay open. Any other tool that logs in (for
  example `client/fm.py`) logs the browser out.

## Persistence: the boot keeper

The root filesystem is squashfs with a tmpfs overlay, so anything copied into
`/webs` or `/etc` is gone after a reboot. What survives is `/data`.

- The stock `/etc/init.d/1restore` extracts `/data/sysupgrade.tgz` onto `/`
  at boot, then deletes it.
- The installers keep a permanent copy, **`/data/sysupgrade.tgz.real`** (the
  "keeper"), holding every added or patched file plus `/etc/rc.local`.
- `rc.local` (in the keeper) copies the keeper back to
  `/data/sysupgrade.tgz` on every boot, so the next boot restores it again.
  It also restores the UCI configs kept in `/data/config/` (DDNS, adblock)
  and starts the VPN service.
- `install.sh` builds the keeper **from scratch**. The other scripts
  (`install-adblock.sh`, `install-speedtest.sh`, `install-agvpn.sh`,
  `update-ui.sh`) unpack the current keeper, add their files and repack it,
  so other members are kept. Each script backs up first to
  `/data/<name>-backup-<stamp>/`.
- To undo everything at the next boot, remove `/data/sysupgrade.tgz` and
  `/data/sysupgrade.tgz.real` and reboot.

## Cache busting

Browsers cache the add-on files aggressively. The pages load them with a
`?v=N` query string; bump N whenever a file changes:

- in the add-on pages (`ddns.html`, `adblock.html`, `vpn.html`) for the files
  they include, and
- for `index.html`, through `patch-index.sh`'s variables `FM_THEME_CSS_V`,
  `FM_THEME_JS_V`, `FM_MENU_V` and `FM_MAIN_V` (the patched `main.*.js`),
  then re-run `update-ui.sh`.

## Speed test fix

On the tested firmware the Diagnostics → Speed Test page didn't work.
`install-speedtest.sh` fixes it:

- **CGI:** `speed_test_status_web_app.cgi` runs the measurement on the router
  (download and upload with `curl` against Cloudflare's public speed
  endpoints, and a ping to 1.1.1.1, over the default-route interface). The
  router's own `/usr/bin/ookla` can't start because its configuration URL
  returns 403. Results are returned in the JSON shape the page expects, and a
  history of 20 runs is kept in `/data/speedtest/`. A run can move about 100 MB down and
  20 MB up. Debug state is in `/tmp/speedtest/`; `update-ui.sh` prints it.
- **Bundle patch:** only `GetSpeedTestResult()` and `startSpeedTest()` in the
  live `main.*.js` are redirected to `speed_test_status_web_app.cgi`; every
  other call still goes to `service_function_web_app.cgi`, which runs nothing
  on this unit. The script checks for the patched method bodies (the stock
  bundle already names the CGI elsewhere, so grepping the name alone would
  give a false "already patched").
- **Empty privacy dialog:** the history table reads
  `Servers[0].server.location`. Without that field, every change-detection
  pass threw and Angular stalled, leaving an empty dialog that couldn't be
  closed. The CGI now adds `"Servers":[{"server":{"location":…}}]` to every
  row.

Check on the router:

```sh
grep -o 'API_ENDPOINT+"speed_test_status_web_app.cgi"' /webs/web_whw/main.*.js | wc -l   # 2
```

## DDNS

The firmware ships OpenWrt's full `ddns-scripts` (around 70 providers), but
the stock UI has no page for it, and the native DDNS CGI only supports a
couple of providers. `ddns.html` and `ddns_uci_web_app.cgi` read and write
the `ddns` UCI config directly. The config is kept in `/data/config/ddns` and
restored by `rc.local` at boot.

## Adblock

`install-adblock.sh` installs OpenWrt's adblock 4.1 (with GNU sort, which it
requires) and the Security → Adblock page. The service is installed switched
off; saving the page with the switch on downloads the lists and restarts
dnsmasq. Lists are fetched to `/tmp` on each start, so they aren't stored in
the keeper.
