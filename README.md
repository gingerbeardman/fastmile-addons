# FastMile 5G Gateway 3.2 add-ons

Custom web UI add-ons and services for the **Nokia FastMile 5G Gateway 3.2**:

- **Web UI:** a flat, always-expanded side menu (including the hidden
  superadmin pages), a dark mode that follows the OS, session keep-alive and
  automatic re-login, so the UI stops logging you out.
- **Dynamic DNS:** a page for OpenWrt's `ddns-scripts`, which the firmware
  ships but doesn't expose.
- **Adblock:** OpenWrt adblock 4.1 with a settings page.
- **VPN:** route chosen LAN devices (or the whole home) through AdGuard VPN,
  using either AdGuard's CLI (65 locations) or IPsec/IKEv2 with strongSwan,
  with automatic fallback to the normal connection.
- **Speed test fix:** makes Diagnostics → Speed Test work again.
- **xbar/SwiftBar plugin:** control the VPN from the macOS menu bar.

Tested on: Nokia FastMile 5G Gateway 3.2, software **1.2202.00.0287**
(OpenWrt 21.02.2, kernel 5.4, aarch64). Other firmware may differ.

## Requirements

- **A root shell on the gateway.** How to get one is out of scope for this
  project. See [this blog post](https://blog.gingerbeardman.com/2026/11/06/extending-the-nokia-fastmile-5g-gateway-32/) for more information.
- A Mac (or other Unix machine) with `curl`, `tar`, `python3` and
  `shasum`/`sha256sum`, to download packages and copy files to the router.
- For the VPN: an AdGuard VPN subscription.

## Install

1. **Download the third-party packages** (on the Mac). This fills
   `device/pkg/` with strongSwan, adblock and GNU sort from the official
   OpenWrt 21.02.2 feed, and the AdGuard VPN CLI from its GitHub releases.
   Checksums are verified. None of these are redistributed here.

   ```sh
   sh device/fetch-packages.sh
   ```

2. **Optional, for VPN IPsec mode:** copy
   `device/agvpn/ipsec-servers.example` to `device/agvpn/ipsec-servers` and
   fill in your server hostnames from the AdGuard dashboard, then create the
   credentials file:

   ```sh
   AGVPN_USER=... AGVPN_PASS=... sh device/make-ipsec-secret.sh
   ```

3. **Copy `device/` to the gateway**, for example to `/tmp/fm/` (it's tmpfs,
   so it's gone after a reboot, which is fine: the installers put what they
   need in `/data`).

4. **Run the installers as root** on the gateway, in this order:

   ```sh
   cd /tmp/fm
   sh install.sh             # menu, theme, auto-login, DDNS; builds the boot keeper
   sh install-speedtest.sh   # speed test fix
   sh install-adblock.sh     # adblock (installed switched off)
   # VPN: log in to the AdGuard CLI once first (docs/vpn.md), then
   sh install-agvpn.sh
   ```

   `install.sh` rebuilds the boot keeper from scratch, so run it first; the
   others add to it. Every script backs up what it replaces to
   `/data/<name>-backup-<stamp>/`.

5. Open `http://192.168.1.1/web_whw/` and log in once on the normal login
   screen. Later UI updates only need `sh update-ui.sh`.

To remove everything: run `agvpn teardown`, delete `/data/sysupgrade.tgz`
and `/data/sysupgrade.tgz.real`, and reboot. The overlay is rebuilt from the
stock firmware; the settings and backups left in `/data` can be deleted by
hand.

## Layout

```
device/
  www/                 pages and scripts deployed into /webs/web_whw/
  cgi/                 CGIs deployed into /webs/ (DDNS, adblock, VPN, speed test)
  agvpn/               VPN supervisor, procd init script, IPsec server list example
  certs/               public CA roots trusted for AdGuard's IPsec servers
  patch-index.sh       patches the router's own index.html in place (keeps .orig)
  fetch-packages.sh    downloads and unpacks third-party packages into pkg/ (Mac)
  make-ipsec-secret.sh writes ipsec.secret from AGVPN_USER/AGVPN_PASS (Mac)
  install*.sh          installers (run on the gateway as root)
  update-ui.sh         refresh pages, menu and theme only
client/
  fm.py                CLI: login, read-only settings snapshot, raw CGI calls
  fmbackup.py          backup/restore of /data and /configs over a root ssh shell
  xbar/                menu-bar plugin for the VPN
server/
  mockd.py             mock gateway backend for local development
  harness.mjs          headless test of the real login code against the mock
docs/
  web-ui.md            menu, theme, sessions, persistence, cache busting, speed test
  vpn.md               VPN architecture, modes, fallback, DNS, findings, gotchas
  development.md       mock server and harness
credentials.example    environment variables the tools read
```

## Notes

- Nothing from Nokia's firmware is included. The router's own `index.html`
  and `main.*.js` are patched in place on the device.
- The web password is stored only in your browser's `localStorage`, never in a
  file served by the router.
- The router allows one web session at a time: any tool that logs in logs
  your browser out. The VPN plugin uses an API token to avoid that.

## Disclaimer

This is an unofficial project. It is not affiliated with, endorsed by or
supported by Nokia, AdGuard or your network operator. It modifies your
gateway's software: use it at your own risk. It may void your warranty,
break with a firmware update, or leave the gateway needing a factory reset.

## Licence

MIT, see [LICENSE](LICENSE). Third-party packages downloaded by
`fetch-packages.sh` keep their own licences.
