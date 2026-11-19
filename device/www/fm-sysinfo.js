/* fm-sysinfo.js — "System" card on Status → General: router CPU, load,
 * memory and uptime from sysinfo_web_app.cgi (/proc only, never the modem).
 *
 * The card takes the first slot of the stock grid (area "total", two columns
 * beside eSIM). The stock Data Usage card that lived there is hidden: it
 * repeats the Cellular WAN totals. It reuses the
 * stock card classes and copies the component's _ngcontent attribute so the
 * page's own (and fm-theme's dark) styles apply. Polls every 5 s, only while
 * the page is open and the tab is visible.
 */
(function () {
  var CGI = "/sysinfo_web_app.cgi";
  var POLL_MS = 5000;
  var timer = null, busy = false, last = null;

  var CSS =
    ".fm-sys{grid-area:total!important}" +
    "app-status-general .total.status__card{display:none!important}" +
    ".fm-sys .fm-sys-grid{display:grid;grid-template-columns:1fr 1fr;gap:36px 48px}" +
    ".fm-sys .fm-sys-k{font-size:13px;line-height:18px;color:#666}" +
    ".fm-sys .fm-sys-v{font-size:30px;line-height:38px;font-weight:700;color:#333;" +
      "font-variant-numeric:tabular-nums;margin:2px 0 6px}" +
    ".fm-sys .fm-sys-v small{font-size:14px;font-weight:400;color:#666;margin-left:4px}" +
    ".fm-sys .fm-sys-s{font-size:13px;line-height:18px;color:#666;font-variant-numeric:tabular-nums}" +
    ".fm-sys .fm-sys-bar{height:6px;border-radius:3px;background:#e6e6e6;overflow:hidden;margin:4px 0 8px}" +
    ".fm-sys .fm-sys-bar i{display:block;height:100%;background:var(--primary,#0168ff);" +
      "border-radius:3px;transition:width .4s ease}" +
    ".fm-sys .fm-sys-cores{display:flex;gap:4px;align-items:flex-end;height:32px;margin:4px 0 8px}" +
    ".fm-sys .fm-sys-cores i{flex:1;background:#e6e6e6;border-radius:2px;position:relative;height:100%}" +
    ".fm-sys .fm-sys-cores i b{position:absolute;left:0;right:0;bottom:0;background:var(--primary,#0168ff);" +
      "border-radius:2px;transition:height .4s ease}" +
    ".fm-sys .fm-sys-note{text-align:end;font-size:13px;color:#999;font-weight:400;align-self:center}" +
    ".fm-sys .fm-sys-hot i,.fm-sys .fm-sys-hot i b{background:#e5484d}" +
    "html.fm-dark .fm-sys .fm-sys-k,html.fm-dark .fm-sys .fm-sys-s," +
      "html.fm-dark .fm-sys .fm-sys-v small{color:#b0b6c2}" +
    "html.fm-dark .fm-sys .fm-sys-v{color:#e6e8ee}" +
    "html.fm-dark .fm-sys .fm-sys-note{color:#8b93a1}" +
    "html.fm-dark .fm-sys .fm-sys-bar,html.fm-dark .fm-sys .fm-sys-cores i{background:#2c313c}" +
    "";

  function onPage() {
    return /^#\/?status\/general/.test(location.hash) &&
      document.querySelector("app-status-general .status-grid-container");
  }

  function ngAttr(el) {
    for (var i = 0; i < el.attributes.length; i++) {
      if (el.attributes[i].name.indexOf("_ngcontent") === 0) return el.attributes[i].name;
    }
    return null;
  }

  function mk(tag, cls, attr, parent, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (attr) e.setAttribute(attr, "");
    if (text != null) e.textContent = text;
    if (parent) parent.appendChild(e);
    return e;
  }

  function build(grid) {
    var a = ngAttr(grid);
    var card = mk("div", "status__card fm-sys", a);
    var inner = mk("div", "card", a, card);
    var head = mk("div", "status__card__row-title", a, inner);
    mk("div", "title", a, head, "System");
    mk("div", "fm-sys-note", a, head, "Router CPU and memory, every 5 s");
    var g = mk("div", "fm-sys-grid", a, inner);
    function block(key) {
      var b = mk("div", "fm-sys-b", a, g);
      mk("div", "fm-sys-k", a, b, key);
      return b;
    }
    var cpu = block("CPU");
    mk("div", "fm-sys-v", a, cpu).id = "fmSysCpu";
    mk("div", "fm-sys-cores", a, cpu).id = "fmSysCores";
    mk("div", "fm-sys-s", a, cpu).id = "fmSysCpuS";
    var load = block("Load average");
    mk("div", "fm-sys-v", a, load).id = "fmSysLoad";
    mk("div", "fm-sys-bar", a, load).id = "fmSysLoadBar";
    mk("div", "fm-sys-s", a, load).id = "fmSysLoadS";
    var mem = block("Memory");
    mk("div", "fm-sys-v", a, mem).id = "fmSysMem";
    mk("div", "fm-sys-bar", a, mem).id = "fmSysMemBar";
    mk("div", "fm-sys-s", a, mem).id = "fmSysMemS";
    var up = block("Uptime");
    mk("div", "fm-sys-v", a, up).id = "fmSysUp";
    mk("div", "fm-sys-s", a, up).id = "fmSysUpS";
    grid.insertBefore(card, grid.firstChild);
    if (last) render(last); else placeholder();
  }

  function $(id) { return document.getElementById(id); }
  function set(id, html) { var e = $(id); if (e) e.innerHTML = html; }
  function bar(id, pct, hot) {
    var e = $(id); if (!e) return;
    if (!e.firstChild) e.appendChild(document.createElement("i"));
    e.firstChild.style.width = Math.max(0, Math.min(100, pct)) + "%";
    e.classList.toggle("fm-sys-hot", !!hot);
  }
  function mb(kb) { return kb >= 1048576 ? (kb / 1048576).toFixed(1) + " GB" : Math.round(kb / 1024) + " MB"; }
  function dur(s) {
    var d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60);
    return d ? d + "d " + h + "h" : h ? h + "h " + m + "m" : m + "m";
  }

  function placeholder() {
    ["fmSysCpu", "fmSysLoad", "fmSysMem", "fmSysUp"].forEach(function (id) { set(id, "–"); });
    set("fmSysCpuS", "Loading…");
  }

  function render(d) {
    var n = d.cpu.n || d.cpu.cores.length || 1;
    set("fmSysCpu", d.cpu.pct.toFixed(0) + "<small>%</small>");
    var cores = $("fmSysCores");
    if (cores) {
      if (cores.children.length !== d.cpu.cores.length) {
        cores.innerHTML = "";
        d.cpu.cores.forEach(function () { cores.appendChild(document.createElement("i")).appendChild(document.createElement("b")); });
      }
      d.cpu.cores.forEach(function (p, i) {
        var b = cores.children[i];
        b.firstChild.style.height = Math.max(2, p) + "%";
        b.title = "Core " + i + ": " + p.toFixed(0) + "%";
      });
      cores.classList.toggle("fm-sys-hot", d.cpu.pct >= 90);
    }
    set("fmSysCpuS", n + " cores · " + d.procs.total + " processes");

    set("fmSysLoad", d.load[0].toFixed(2));
    // No red here: on this MediaTek board load sits near 8-9 at low CPU, since
    // kernel threads waiting on the modem hardware count as load.
    bar("fmSysLoadBar", 100 * d.load[0] / (2 * n), false);
    set("fmSysLoadS", "5 min " + d.load[1].toFixed(2) + " · 15 min " + d.load[2].toFixed(2));

    var used = d.mem.total - d.mem.avail, pct = d.mem.total ? 100 * used / d.mem.total : 0;
    set("fmSysMem", pct.toFixed(0) + "<small>%</small>");
    bar("fmSysMemBar", pct, pct >= 90);
    set("fmSysMemS", mb(used) + " of " + mb(d.mem.total) + " · " + mb(d.mem.avail) + " available");

    set("fmSysUp", dur(d.uptime));
    var since = new Date(Date.now() - d.uptime * 1000);
    set("fmSysUpS", "since " + since.toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }));
  }

  function poll() {
    if (busy || document.visibilityState !== "visible" || !onPage()) return;
    busy = true;
    fetch(CGI, { credentials: "include", cache: "no-store" })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d && d.result === 0) { last = d; render(d); }
        else set("fmSysCpuS", d && d.result === -401 ? "Not logged in" : "Unavailable");
      })
      .catch(function () { set("fmSysCpuS", "Unavailable"); })
      .then(function () { busy = false; });
  }

  function check() {
    var grid = onPage();
    if (grid && !grid.querySelector(".fm-sys")) build(grid);
    if (grid && !timer) { poll(); timer = setInterval(poll, POLL_MS); }
    if (!grid && timer) { clearInterval(timer); timer = null; }
  }

  var style = document.createElement("style");
  style.textContent = CSS;
  document.head.appendChild(style);
  if (document.querySelector("app-root")) {
    var pending = false;
    new MutationObserver(function () {
      if (pending) return;
      pending = true;
      requestAnimationFrame(function () { pending = false; check(); });
    }).observe(document.documentElement, { childList: true, subtree: true });
  }
  window.addEventListener("hashchange", check);
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") poll();
  });
})();
