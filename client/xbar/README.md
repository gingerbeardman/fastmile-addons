# AdGuard VPN menu-bar plugin

`agvpn.30s.py` is an xbar/SwiftBar plugin for the AdGuard VPN on the FastMile
router. It talks to `http://192.168.1.1/agvpn_web_app.cgi` with a normal web
session. It's a single file, stdlib Python only (`/usr/bin/python3`), and
refreshes every 30 s.

## Setup

1. Store the router password in the Keychain (the username defaults to
   `superadmin`; set `FM_USER` to override it):

   ```sh
   security add-generic-password -U -s fastmile-router -a superadmin -w
   ```

   Leaving `-w` without a value makes `security` prompt for the password, so
   it stays out of your shell history.

2. Link the plugin into the plugin folder (xbar and SwiftBar both use
   `~/Library/Application Support/xbar/plugins` here):

   ```sh
   ln -sf "$PWD/agvpn.30s.py" ~/Library/Application\ Support/xbar/plugins/
   ```

The first run may show a Keychain prompt; choose "Always Allow". The session
(`sid` cookie + csrf token) is cached in
`~/Library/Caches/fastmile-agvpn/session.json` (mode 600). It logs in again
automatically when the router returns 401.

## Menu

- **Title:** ⛊ when connected (⛊ … while connecting), ⛉ when off, ⛉ ! on fallback or error, and ⛉ ? if the router can't be reached. **Show region in menu bar** (off by default) adds the country code, e.g. ⛊ GB. The setting isn't saved, so it resets when you log out or restart. SwiftBar shows SF Symbols instead.
- **Status:** state, location, mode, tunnel IP, uptime, and any error.
- **Connect / Disconnect.**
- **Location:** "Fastest available", then locations under 50 ms. Slower ones
  are in a "Slower locations (50 ms+)" submenu. **Sort by** (at the bottom)
  switches between ping order (the default) and alphabetical by country,
  where countries with several cities get a submenu. The choice is saved in
  `~/Library/Application Support/fastmile-agvpn/prefs.json`. ✓ marks the
  current location.
- **Mode:** CLI or IPsec. Switching picks the new mode's server for the
  same country, or the fastest one if there isn't one.
- **Devices:** the devices that use the VPN (scope `devices`); click a device
  to remove it from the list, or add one from "Not on VPN". The last device
  can't be removed. With scope `all`, it's read-only.
- **Open VPN page**, **Refresh**.

After an action the script polls the router for up to 15 s, then the menu
refreshes. If the router doesn't confirm the change, you get a notification.

## Command line

```sh
./agvpn.30s.py                  # print the menu
./agvpn.30s.py connect|disconnect
./agvpn.30s.py location Paris
./agvpn.30s.py mode cli|ipsec
./agvpn.30s.py device 192.168.1.50
AGVPN_DRY_RUN=1 ./agvpn.30s.py mode ipsec   # print the POST, don't send it
```

Env: `FM_HOST`, `FM_USER`, `FM_PASS` (overrides the Keychain), `AGVPN_DRY_RUN`.

## Why the plugin doesn't log in by itself

The router allows **one web session at a time**: a new login ends the
previous one. A plugin that logged in every time its session ended would keep
logging your browser out, and the browser would log it out in turn. So:

- **With an API token (recommended):** the plugin sends `X-AGVPN-Token` and
  never logs in. The VPN CGI accepts the token instead of a session.
  - Device names come from a copy the CGI keeps from your last visit to the
    VPN page.
  - The router side is `/data/adguardvpn-cli/api.token` (root, mode 600). The
    Mac side is the Keychain item `fastmile-agvpn-token` (account `router`).

  Set it up once:

  ```sh
  security add-generic-password -U -s fastmile-agvpn-token -a router -w "$(openssl rand -hex 32)"
  ```

  Then write the same value to the router's `/data/adguardvpn-cli/api.token`
  (as root, mode 600).
- **Without a token:** it reuses its last session. When that ends, the menu
  shows ⛉ ? "Router session ended", with a **Log in now** item. That item logs
  the browser out, so the plugin only does it when you click.
