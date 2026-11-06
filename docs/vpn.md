# AdGuard VPN on the gateway

`agvpn` routes chosen LAN devices (or the whole home) through AdGuard VPN, and
falls back to the normal connection when the tunnel fails. It is controlled
from the **VPN** page in the web UI (Application → VPN), from the command line
on the router, or from the xbar/SwiftBar menu-bar plugin.

You need an AdGuard VPN subscription. Nothing here is affiliated with AdGuard.

## Architecture

```
LAN device ──br-lan──▶ policy routing / SNAT ──▶ tunnel ──▶ AdGuard exit
                             │ (tunnel down)
                             └────────────────▶ normal WAN (fallback)
```

- `/usr/sbin/agvpn` (from `device/agvpn/agvpn`) is the supervisor. procd runs
  `agvpn run` via `/etc/init.d/agvpn` (`device/agvpn/agvpn.init`), with
  respawn.
- Router traffic itself keeps using the normal WAN. Only the chosen devices'
  traffic is sent through the tunnel.
- Settings live in `/data/adguardvpn-cli/agvpn.conf`: `ENABLED`, `MODE`
  (`cli`|`ipsec`), `LOCATION` (name, ISO code or `fastest`), `SCOPE`
  (`devices`|`all`) and `DEVICES` (space-separated IPs). Runtime state is in
  `/tmp/agvpn-svc/` (`state.json`, `log`, `connect.out`, `locations.json`).
- `/webs/agvpn_web_app.cgi` (from `device/cgi/`) is the HTTP API used by
  `vpn.html` and the xbar plugin.

### Commands

```sh
agvpn status                    # JSON
agvpn enable | disable
agvpn set mode cli|ipsec
agvpn set location <name>       # cli: city, country, ISO code or "fastest"
                                # ipsec: gb, de, nl, fi, us (or a city/country word)
agvpn set scope all|devices
agvpn set devices "<ip> <ip>"
agvpn locations [refresh]       # JSON
agvpn teardown                  # remove every rule agvpn added
```

## Modes

### CLI mode (default)

Uses AdGuard's own Linux CLI (`adguardvpn-cli`, static `linux-aarch64` build,
fetched by `device/fetch-packages.sh`) and AdGuard's own protocol.

- About 65 locations, with a built-in "fastest" pick.
- Uses one of your AdGuard device slots.
- TUN mode with the CLI's own routing turned off
  (`set-mode TUN`, `set-tun-routing-mode NONE`, `set-tun-device-name agvpn0`,
  `set-change-system-dns off`). agvpn sets these on every start.
- Chosen sources get an `ip rule` to table 100, whose default route via
  `agvpn0` exists only while the tunnel is healthy. Traffic is MASQUERADEd out
  of `agvpn0` and MSS is clamped to the path MTU.
- The binary is kept in `/data/adguardvpn-cli/` but copied to `/tmp/agcli/`
  to run, because `/data` is mounted noexec.
- The login is in `/data/adguardvpn-cli/data`, linked from
  `/root/.local/share/adguardvpn-cli` so it survives reboots.

**Logging in (once, interactive):** the CLI's `login` command has no
non-interactive form. On the router, as root, after copying `device/` over:

```sh
mkdir -p /data/adguardvpn-cli/data /root/.local/share /tmp/agcli
chmod 700 /data/adguardvpn-cli /data/adguardvpn-cli/data
ln -sfn /data/adguardvpn-cli/data /root/.local/share/adguardvpn-cli
cp pkg/adguardvpn-cli /data/adguardvpn-cli/adguardvpn-cli
cp pkg/adguardvpn-cli /tmp/agcli/adguardvpn-cli && chmod 755 /tmp/agcli/adguardvpn-cli
HOME=/root /tmp/agcli/adguardvpn-cli login
```

Then run `sh install-agvpn.sh`.

### IPsec mode

Standard IKEv2 to one of AdGuard's five router/IPsec servers, using
strongSwan 5.9.2 from OpenWrt 21.02.2 (fetched by `fetch-packages.sh`).

- Runs in the kernel and uses no AdGuard device slot, but only five locations.
- Login is EAP-MSCHAPv2 with a username and password from the AdGuard
  dashboard. One credential set worked on every server in testing, although
  AdGuard doesn't document that, so it could change.
- Server hostnames have random suffixes and come from the dashboard. Put them
  in `device/agvpn/ipsec-servers` (start from `ipsec-servers.example`; the
  format is `<code> <hostname> <City_Name> <Country name>`).
- Create the credentials file on the Mac with
  `AGVPN_USER=... AGVPN_PASS=... sh device/make-ipsec-secret.sh`.
  `install-agvpn.sh` copies it to `/data/adguardvpn-cli/ipsec.secret`
  (mode 600) and deletes the upload. `swanctl.conf`, which contains the
  secret, is generated in tmpfs on each connect and never archived.
- There is no tunnel interface: chosen sources are SNAT'd to the virtual IP
  on the WAN so they match the IPsec policy. MSS is clamped to 1360 both
  ways. `strongswan.conf` sets `install_routes = no` and puts the virtual IP
  on `lo`.
- Trusted roots (in `device/certs/`, copied into `etc/swanctl/x509ca/`):
  Comodo AAA Certificate Services, USERTrust RSA and ECC, ISRG X1/X2,
  DigiCert Global Root G2 and GTS Root R1. Some servers send a short chain
  (ZeroSSL → Sectigo R46) without the USERTrust cross-certificate, so the
  Comodo AAA root alone isn't enough; USERTrust RSA is needed too.
- Proposals seen: IKE `AES_GCM_16-128/PRF_HMAC_SHA1/MODP_2048`, ESP
  `AES_CBC-128/HMAC_SHA2_256_128`. NAT-T on UDP 4500 works through carrier
  NAT.

## Fallback

- Health check every 10 s: `curl --interface agvpn0 http://1.1.1.1/cdn-cgi/trace`
  in CLI mode (IPsec mode checks for an installed SA).
- agvpn falls back at once if `agvpn0` disappears, or after 3 failed checks:
  the VPN routes, SNAT and DNS rules are removed, so devices use the normal
  WAN. It then retries with backoff from 5 s up to 300 s.
- Measured: after `killall -9 adguardvpn-cli`, a test client was back on the
  normal WAN within about 3 s with no failed requests, and the tunnel came
  back about 10 s later.

## DNS

- While the tunnel is up, VPN'd devices' DNS (port 53 to any destination,
  including hard-coded resolvers such as 8.8.8.8) is redirected through the
  tunnel. CLI mode uses the resolver the CLI provides; IPsec mode uses AdGuard
  DNS (`94.140.14.140`), reached through the tunnel. Without this, DNS would
  leak to the carrier.
- With `SCOPE=all`, LAN DNS bypasses the router's dnsmasq, so router adblock
  and `.lan` names don't apply to VPN'd devices.
- The IPsec server's `INTERNAL_IP4_DNS` attribute is ignored on purpose (the
  strongSwan resolve plugin isn't installed).

## API token for the menu-bar plugin

The router allows **one web session at a time**: any new login ends the
previous one. A tool that logs in therefore logs your browser out. So the CGI
also accepts an `X-AGVPN-Token` header that matches
`/data/adguardvpn-cli/api.token` (root, mode 600), and serves a cached device
list (`/tmp/agvpn-svc/devices.cache`, refreshed whenever the VPN page is
opened in a browser). See `client/xbar/README.md` for setup.

All other requests need a valid web session: the CGI forwards the request's
cookie to the stock `device_name_status_web_app.cgi`, which returns 401
without one. POSTs need the session's `csrf_token`, and requests with a
foreign Origin/Referer are refused (403).

## Measured findings

Numbers are from one unit on a 5G connection in the UK; yours will differ.

| Path | 1 connection | 4 connections |
|---|---|---|
| No VPN | ~50–140 Mbps | ~410 Mbps |
| CLI mode, nearby location | ~120–150 Mbps | ~145–175 Mbps |
| IPsec, good server (e.g. London, Frankfurt, New York) | ~45–105 Mbps | ~105–185 Mbps |
| IPsec, capped server (Amsterdam, Helsinki at the time) | ~3–10 Mbps | ~20–40 Mbps |

- Some AdGuard IPsec servers cap each TCP connection at about 5–10 Mbps, and
  speed scales with the number of connections. It isn't the router: CPU,
  cipher (CBC vs GCM) and receive windows made no difference, and the same
  router reaches 100+ Mbps on other IPsec servers. The VPN page marks those
  servers as slow.
- The gateway has no ARMv8 crypto-extension drivers, so AES/SHA run in
  software. It still isn't the bottleneck at these speeds.
- The router CLI matched or beat AdGuard's own desktop app on the same
  connection.

## Gotchas

- **One web session at a time.** A login from `fm.py`, a script or a plugin
  logs out the browser (see above). Sessions also expire after 900 s idle.
- **CGI RLIMIT_NOFILE 256.** lighttpd runs CGIs with a 256 file-descriptor
  limit. procd's `procd_lock` does `exec 1000>lock`, which then fails, so
  `/etc/init.d/agvpn restart` from a CGI silently does nothing. The VPN and
  adblock CGIs start with `ulimit -n 1024`. The VPN CGI also waits up to 5 s
  for `state.json` to change and returns `result:-5` ("settings saved but the
  VPN service did not restart") if it doesn't.
- **procd starts services with `HOME=/`.** The CLI then can't find its login
  ("Please log in"), so agvpn exports `HOME=/root`.
- **IPv6 ESP-in-UDP needs kernel 5.8+.** The gateway runs 5.4, and AdGuard's
  hostnames have AAAA records, so agvpn resolves the server's IPv4 address
  and puts it in `remote_addrs`. `remote.id` stays the hostname, so the
  certificate check still applies.
- **Missing iptables userspace matches.** The kernel has the modules, but the
  userspace iptables has no `policy` match (`-m policy --pol ipsec`) and no
  `state` match. So the tunnel address is exempted from the stock NAT with a
  plain `-s <vip>/32 -j ACCEPT` at the top of `POSTROUTING`, and return
  traffic relies on the stock chains already accepting established flows.
  Without the exemption the stock WAN NAT rewrites the packets before
  encryption and they leave in clear.
- **`/data` is noexec.** Binaries stored there (the CLI) must be copied to
  `/tmp` to run.
- **The connect message differs by mode.** TUN mode prints "Successfully
  Connected to LONDON"; the parser matches `[Cc]onnected to <NAME>`.
- **The IPsec servers drop ICMP.** Ping through the tunnel fails even when TCP
  works.
- **Revocation (OCSP/CRL) fetches fail** because no fetcher plugin is
  installed. strongSwan treats that as a soft failure.
- **Long shell commands get truncated.** Commands over about 1 KB typed or
  pasted into the router's ash shell get cut off. Upload a script and run it.
- **Bigger TCP buffers made things worse** on the capped servers (a 2 MB
  default `tcp_rmem` stalled completely). Leave the defaults.
