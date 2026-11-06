/* fm-menu.js — flat side menu shared by the stock app and our own pages.
 *
 * Replaces the stock collapsible menu with one always-expanded list where
 * hierarchy is shown only by indentation, in a narrower sidebar. Adds the
 * Dynamic DNS entry under Application.
 *
 * Stock pages (index.html): the menu is injected into Angular's sidenav after
 * the logo, and the stock list is hidden; Angular's logo, login/logout and
 * language picker are kept as-is.
 * Our pages: call FMMenu.render(el) to fill a container.
 *
 * Items mirror the stock defaultMenu (main.js), minus superadmin-only entries.
 * Labels come from the stock i18n files (SIDEMENU.*), English fallback.
 */
(function () {
  var WIDTH = 220;
  var ROOT = "/web_whw/";

  // [depth, i18n key, route (null = heading), fallback label]
  var MENU = [
    [0, "OVERVIEW", "overview", "Overview"],
    [0, "STATUS", null, "Status"],
    [1, "GENERAL", "status/general", "General"],
    [1, "CELLULAR", "status/cellular", "Cellular"],
    [0, "STATISTICS", "statistics", "Statistics"],
    [0, "MESSAGES", "messages", "Messages"],
    [0, "NETWORK", null, "Network"],
    [1, "WIFI", null, "Wi-Fi Networks"],
    [2, "24GHZ", "network/wifi-networks/2.4Ghz", "2.4GHz"],
    [2, "5GHZ", "network/wifi-networks/5Ghz", "5GHz"],
    [2, "WIFI_SCHEDULE", "network/wifi-networks/wifi-schedule", "Wi-Fi Schedule"],
    [1, "CELLULAR", null, "Cellular"],
    [2, "", "network/cellular/accessPoint", "APN"],   // stock label too wide
    [2, "CELL_MGMT", "network/cellular/cellManagement", "Cell Management", "superadmin"],
    [1, "ETHERNET_WAN", "network/ethernetWAN", "Ethernet WAN"],
    [1, "STATICROUTE", "network/staticRoutes", "Static Routes"],
    [1, "LAN_SETTINGS", null, "LAN Settings"],
    [2, "LAN", "network/lan-settings/lan", "LAN"],
    [2, "IPV6LAN", "network/lan-settings/lan-ipv6", "LAN IPv6"],
    [1, "ACS", "network/controller", "ACS", "superadmin"],   // stock: access superadmin
    [1, "CONNECTED_DEVICES", "network/connected-devices", "Connected Devices"],
    [0, "APPLICATION", null, "Application"],
    [1, "PORT_FORWARDING", "application/portforwarding", "Port Forwarding"],
    [1, "PORT_TRIGGERING", "application/porttriggering", "Port Triggering"],
    [1, "NTP", "application/ntp", "NTP"],
    [1, "DDNS", "ddns.html", "Dynamic DNS"],
    [1, "VPN", "vpn.html", "VPN"],
    [0, "SECURITY", null, "Security"],
    [1, "ACCESS_CONTROL", "security/accessControl", "Access Control", "superadmin"],
    [1, "FIREWALL", "security/firewall", "Firewall"],
    [1, "ADBLOCK", "adblock.html", "Adblock"],
    [1, "IPFILTER", "security/IPFilter", "IP Filter"],
    [1, "DMZ_ALG", "security/dmz-alg", "DMZ/ALG"],
    [0, "DIAGNOSTICS", null, "Diagnostics"],
    [1, "LOG", "diagnostics/log", "Logs"],
    [1, "SPEEDTEST", "diagnostics/speedtest", "Speed Test"],
    [0, "SYSTEM", null, "System"],
    [1, "GENERAL", "system/general", "General"],
    [1, "DEVICE_MANAGEMENT", "system/deviceManagement", "Device Management"],
    [1, "LED_MANAGEMENT", "system/ledManagement", "LED Management"]
  ];

  // Labels to use instead of the stock translation (menu and page heading).
  var RENAME = { ACS: "ACS" };   // stock: "ACS - Auto Configuration Server"

  var CSS =
    /* menu (both page types) */
    /* fixed between the logo (94px) and the logout bar (57px), so the list
     scrolls inside the full sidebar height instead of stopping short */
    ".fm-menu{position:fixed;top:94px;bottom:57px;left:0;width:" + WIDTH + "px;" +
      "overflow-y:auto;overscroll-behavior:contain;padding:0 0 12px;box-sizing:border-box}" +
    ".fm-mi{display:flex;align-items:center;height:30px;padding-right:12px;" +
      "font:400 14px/20px -apple-system,BlinkMacSystemFont,Roboto,Arial,sans-serif;" +
      "color:#757575;text-decoration:none;white-space:nowrap;overflow:hidden;" +
      "text-overflow:ellipsis;outline:none}" +
    /* headings (no route): smaller and greyed out, so they read as labels */
    ".fm-mi.fm-mh{height:26px;font-size:12px;color:#b3b3b3;cursor:default}" +
    "a.fm-mi:hover,a.fm-mi:focus{color:#333;background:#ebebeb}" +
    "a.fm-mi.active{font-weight:700;color:#333;background:#ebebeb}" +
    ".fm-mi .fm-dot{width:8px;height:8px;border-radius:50%;flex:0 0 8px;" +
      "background:var(--primary,#0168ff);margin-right:8px}" +
    /* stock sidenav: narrower, flat menu instead of the collapsible list */
    ".sidenav-menu{width:" + WIDTH + "px!important}" +
    ".sidenav-menu .logout{width:" + (WIDTH - 1) + "px!important}" +
    ".mat-sidenav-content{margin-left:" + WIDTH + "px!important}" +
    ".sidenav-menu .nokia-logo-container{width:150px!important;" +
      "padding:36px 0 30px 24px!important}" +
    ".sidenav-menu .lang-container{margin-right:16px!important}" +
    ".sidenav-menu .sidenav-menu__list{display:none!important}";

  var labels = {};

  function lang() {
    var l = "";
    try { l = localStorage.getItem("language") || ""; } catch (e) {}
    return /^(en|ja)$/.test(l) ? l : "en";
  }
  function href(route) {
    return /\.html$/.test(route) ? ROOT + route : ROOT + "#/" + route;
  }
  function current() {
    if (/\.html$/.test(location.pathname)) return location.pathname.split("/").pop();
    return location.hash.replace(/^#\/?/, "").split("?")[0];
  }
  function indent(depth, active) {   // the active dot takes 16px of the indent
    return (24 + 16 * depth - (active ? 16 : 0)) + "px";
  }

  function build() {
    var nav = document.createElement("nav");
    nav.className = "fm-menu";
    MENU.forEach(function (m) {
      var el = document.createElement(m[2] ? "a" : "div");
      el.className = m[2] ? "fm-mi" : "fm-mi fm-mh";
      if (m[2]) { el.href = href(m[2]); el.setAttribute("data-route", m[2]); }
      if (m[4]) el.setAttribute("data-access", m[4]);
      el.setAttribute("data-depth", m[0]);
      el.style.paddingLeft = indent(m[0], false);
      el.appendChild(document.createTextNode(RENAME[m[1]] || labels[m[1]] || m[3]));
      nav.appendChild(el);
    });
    mark(nav);
    return nav;
  }

  // keep the scroll position across full page loads (stock <-> our pages),
  // and make sure the current item is visible
  function placeScroll(nav) {
    try { nav.scrollTop = +sessionStorage.getItem("fm_menu_top") || 0; } catch (e) {}
    var a = nav.querySelector("a.fm-mi.active");
    if (a) {
      // the nav is positioned, so it is the offsetParent of its items
      var top = a.offsetParent === nav ? a.offsetTop : a.offsetTop - nav.offsetTop;
      if (top < nav.scrollTop || top + a.offsetHeight > nav.scrollTop + nav.clientHeight)
        nav.scrollTop = top - nav.clientHeight / 2;
    }
    nav.addEventListener("scroll", function () {
      try { sessionStorage.setItem("fm_menu_top", nav.scrollTop); } catch (e) {}
    });
  }

  // Items with an access level (ACS) show only to that user, like the stock menu.
  function user() { try { return sessionStorage.getItem("currentUser") || ""; } catch (e) { return ""; } }
  function access(nav) {
    var u = user();
    [].forEach.call(nav.querySelectorAll("[data-access]"), function (el) {
      el.style.display = el.getAttribute("data-access") === u ? "" : "none";
    });
  }

  function mark(nav) {
    access(nav);
    var cur = current();
    [].forEach.call(nav.querySelectorAll("a.fm-mi"), function (a) {
      var on = a.getAttribute("data-route") === cur;
      a.classList.toggle("active", on);
      a.style.paddingLeft = indent(+a.getAttribute("data-depth"), on);
      var dot = a.querySelector(".fm-dot");
      if (on && !dot) {
        dot = document.createElement("span"); dot.className = "fm-dot";
        a.insertBefore(dot, a.firstChild);
      } else if (!on && dot) a.removeChild(dot);
    });
  }
  function markAll() {
    [].forEach.call(document.querySelectorAll(".fm-menu"), mark);
  }

  function relabel() {
    [].forEach.call(document.querySelectorAll(".fm-menu"), function (nav) {
      var items = nav.querySelectorAll(".fm-mi");
      MENU.forEach(function (m, i) {
        var t = items[i] && items[i].lastChild;
        if (t && labels[m[1]]) t.nodeValue = RENAME[m[1]] || labels[m[1]];
      });
    });
  }
  function loadLabels() {
    fetch(ROOT + "assets/i18n/" + lang() + ".json")
      .then(function (r) { return r.json(); })
      .then(function (d) { labels = d.SIDEMENU || {}; relabel(); })
      .catch(function () {});
  }

  // Angular's hash router navigates with pushState, which fires no event
  ["pushState", "replaceState"].forEach(function (k) {
    var orig = history[k];
    history[k] = function () {
      var r = orig.apply(this, arguments); markAll(); return r;
    };
  });
  window.addEventListener("hashchange", markAll);
  window.addEventListener("popstate", markAll);

  var style = document.createElement("style");
  style.textContent = CSS;
  document.head.appendChild(style);
  loadLabels();

  // stock app: (re)insert after the logo whenever Angular renders the sidenav
  function inject() {
    // Overview: open the Radio Access rows (5G/4G) once per render; the user can
    // still collapse them. Marked so a collapse isn't undone.
    if (current() === "overview") {
      [].forEach.call(document.querySelectorAll('mat-expansion-panel-header[aria-expanded="false"]:not([data-fm-auto])'),
        function (hd) { hd.setAttribute("data-fm-auto", "1"); hd.click(); });
    }
    var h = document.getElementById("headingACS");   // ACS page title
    if (h && h.textContent.trim() !== RENAME.ACS) h.textContent = RENAME.ACS;
    var logo = document.querySelector(".sidenav-menu .nokia-logo-container");
    if (logo && !logo.parentNode.querySelector(".fm-menu")) {
      var nav = build();
      logo.parentNode.insertBefore(nav, logo.nextSibling);
      placeScroll(nav);
    }
  }
  if (document.querySelector("app-root")) {
    new MutationObserver(inject).observe(document.documentElement,
      { childList: true, subtree: true });
  }

  // Session keep-alive. The router ends a session after 900 s without an
  // authenticated request; check_expire only reads the countdown, so the stock
  // app's 10 s polling doesn't count and an idle tab gets logged out. Every
  // 4 minutes, and whenever the tab becomes visible, ask check_expire and, if
  // the session is still valid, make one cheap authenticated request to reset
  // the countdown to 900. It never logs in, so it can't end another session.
  var KEEPALIVE_MS = 240000, lastPing = 0;
  function keepAlive() {
    if (Date.now() - lastPing < 60000) return;
    lastPing = Date.now();
    fetch("/check_expire_web_app.cgi", { credentials: "include", cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j && j.expired === "no") {
          return fetch("/device_name_status_web_app.cgi", { credentials: "include", cache: "no-store" });
        }
        // Expired (e.g. the Mac slept): log back in as the same user, if stored.
        if (window.FM && FM.hasCred && FM.hasCred() && FM.relogin) return FM.relogin();
      })
      .catch(function () {});
  }
  setInterval(keepAlive, KEEPALIVE_MS);
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") keepAlive();
  });

  window.FMMenu = {
    width: WIDTH,
    render: function (el) { var nav = build(); el.appendChild(nav); placeScroll(nav); }
  };
})();
