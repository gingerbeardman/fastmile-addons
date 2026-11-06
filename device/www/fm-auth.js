/* fm-auth.js — shared auth + API helper for the custom FastMile pages.
 *
 * Reuses the device's own crypto helpers (assets/js/crypto_page.js, which
 * pulls in sjcl + jsencrypt), so the login hashing is byte-identical to the
 * stock web_whw app. No credentials are embedded in any device-served file:
 * the admin password is entered once and kept in this browser's localStorage
 * (key "fm_pw"); after that, login is automatic. Clear it by calling
 * FM.forget() or clearing site data.
 *
 * The account is remembered too ("fm_user", default admin). Logging in on the
 * stock login screen stores that account and password, so automatic re-login
 * keeps you as the same user (superadmin stays superadmin, so ACS stays).
 *
 * Expired sessions (e.g. after the Mac slept): the stock app polls
 * check_expire_web_app.cgi and logs out on "expired". When a password is
 * stored, that response is held back, a silent re-login is done, and the app
 * sees a fresh check_expire result instead.
 *
 * Exposes window.FM:
 *   FM.ensure()        -> Promise, guarantees a live session (auto-login)
 *   FM.login(pw[,user])-> Promise<bool>, explicit login, stores user+pw on success
 *   FM.get(endpoint)   -> Promise<Response>  (session ensured, GET)
 *   FM.post(ep, obj)   -> Promise<Response>  (session ensured, csrf added)
 *   FM.forget()        -> wipe stored credential + session
 *   FM.hasCred()       -> bool
 */
(function () {
  function getUser() {
    try { return localStorage.getItem("fm_user") || "admin"; } catch (e) { return "admin"; }
  }

  function sha256hex(s) {
    return sjcl.codec.hex.fromBits(sjcl.hash.sha256.hash(s));
  }
  function rand16b64() {   // 4 words = 16 bytes, base64 (un-escaped)
    return sjcl.codec.base64.fromBits(sjcl.random.randomWords(4, 0));
  }
  function getPw() {
    try { return localStorage.getItem("fm_pw") || ""; } catch (e) { return ""; }
  }
  function setPw(p) { try { localStorage.setItem("fm_pw", p); } catch (e) {} }
  function setUser(u) { try { localStorage.setItem("fm_user", u); } catch (e) {} }

  function nonce() {
    return fetch("/login_web_app.cgi?nonce", { credentials: "include" })
      .then(function (r) { return r.json(); });
  }

  function login(pw, user) {
    var USER = user || getUser();
    return nonce().then(function (r) {
      if (!r.nonce) throw new Error("no nonce");
      var l = r.iterations >= 1 ? sha256hex(pw) : pw;
      for (var i = 1; i < r.iterations; i++) l = sha256hex(l); // extra rounds
      var p = cryptoJS.sha256(USER, l.toLowerCase());
      var v = cryptoJS.sha256url(p, r.nonce);
      var W = rand16b64(), Q = rand16b64();      // session AES key + iv
      var body =
        "userhash=" + cryptoJS.sha256url(USER, r.nonce) +
        "&RandomKeyhash=" + cryptoJS.sha256url(r.randomKey, r.nonce) +
        "&response=" + v +
        "&nonce=" + cryptoJS.base64url_escape(r.nonce) +
        "&enckey=" + cryptoJS.base64url_escape(W) +
        "&enciv=" + cryptoJS.base64url_escape(Q);
      return fetch("/login_web_app.cgi", {
        method: "POST", credentials: "include",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: body
      }).then(function (resp) { return resp.json(); })
        .then(function (j) {
          if (j.result === 0) {
            try {
              // mirror the stock app exactly so its response-decryption works
              sessionStorage.setItem(j.sid, W + " " + Q);
              sessionStorage.setItem("sid", j.sid);
              sessionStorage.setItem("token", j.token);
              sessionStorage.setItem("currentUser", USER);
            } catch (e) {}
            setPw(pw);
            setUser(USER);
            return true;
          }
          return false;
        });
    });
  }

  function expired() {
    return fetch("/check_expire_web_app.cgi", { credentials: "include" })
      .then(function (r) { return r.json(); })
      .then(function (j) { return j.expired !== "no"; })
      .catch(function () { return true; });
  }

  function ensure() {
    return expired().then(function (exp) {
      if (!exp) return true;
      var pw = getPw();
      if (!pw) return Promise.reject(new Error("no-cred"));
      return login(pw);
    });
  }

  function token() { try { return sessionStorage.getItem("token") || ""; } catch (e) { return ""; } }

  function get(ep) {
    return ensure().then(function () {
      return fetch("/" + ep.replace(/^\//, ""), { credentials: "include" });
    });
  }

  function post(ep, obj) {
    return ensure().then(function () {
      var parts = [];
      Object.keys(obj || {}).forEach(function (k) {
        parts.push(encodeURIComponent(k) + "=" + encodeURIComponent(obj[k]));
      });
      parts.push("csrf_token=" + encodeURIComponent(token()));
      return fetch("/" + ep.replace(/^\//, ""), {
        method: "POST", credentials: "include",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: parts.join("&")
      });
    });
  }

  function forget() {
    try { localStorage.removeItem("fm_pw"); localStorage.removeItem("fm_user"); } catch (e) {}
    try { sessionStorage.clear(); } catch (e) {}
  }

  // One re-login at a time, however many callers notice the expiry.
  var relogging = null;
  function relogin() {
    if (!getPw()) return Promise.resolve(false);
    if (!relogging) {
      relogging = login(getPw()).catch(function () { return false; })
        .then(function (ok) { relogging = null; return ok; });
    }
    return relogging;
  }

  // Remember the account used on the stock login screen. The password is read
  // from the form when Log In is pressed and stored only once the stock app
  // reports a successful login for that user.
  function watchStockLogin() {
    function grab(ev) {
      var root = ev.target && ev.target.closest && ev.target.closest("app-login");
      if (!root) return;
      if (ev.type === "keydown" && ev.key !== "Enter") return;
      if (ev.type === "click" && !ev.target.closest("button")) return;
      var ins = root.querySelectorAll("input");
      var u = "", p = "";
      [].forEach.call(ins, function (i) {
        if (i.type === "password") p = i.value; else if (!u && i.type !== "checkbox") u = i.value;
      });
      if (!u || !p) return;
      var tries = 0, t = setInterval(function () {
        var cur = "";
        try { cur = sessionStorage.getItem("currentUser") || ""; } catch (e) {}
        if (cur === u) { setUser(u); setPw(p); clearInterval(t); }
        else if (++tries > 40) clearInterval(t);
      }, 250);
    }
    document.addEventListener("click", grab, true);
    document.addEventListener("keydown", grab, true);
  }

  // Hold back an "expired" check_expire answer from the stock app, re-login,
  // and hand it a fresh answer. Network errors on that poll (common for a few
  // seconds after wake) are swallowed rather than treated as a logout.
  function patchExpireXhr() {
    var P = XMLHttpRequest.prototype, open = P.open, add = P.addEventListener;
    P.open = function (m, u) {
      this._fmExpire = /check_expire_web_app\.cgi/.test(String(u));
      return open.apply(this, arguments);
    };
    function override(x, text) {
      Object.defineProperty(x, "responseText", { configurable: true, get: function () { return text; } });
      Object.defineProperty(x, "response", { configurable: true, get: function () {
        return x.responseType === "json" ? JSON.parse(text) : text; } });
    }
    P.addEventListener = function (type, fn, opt) {
      if (this._fmExpire && typeof fn === "function" && (type === "load" || type === "error")) {
        var orig = fn;
        fn = function (ev) {
          var x = this;
          if (!getPw()) return orig.call(x, ev);
          if (type === "error") return;          // retry on the next 10 s poll
          var txt = "";
          try { txt = x.responseText; } catch (e) {}
          if (!/"expired"\s*:\s*"(yes|unknown)"/.test(txt)) return orig.call(x, ev);
          relogin().then(function (ok) {
            if (!ok) return orig.call(x, ev);
            return fetch("/check_expire_web_app.cgi", { credentials: "include", cache: "no-store" })
              .then(function (r) { return r.text(); })
              .then(function (fresh) { override(x, fresh); orig.call(x, ev); });
          }).catch(function () { orig.call(x, ev); });
        };
      }
      return add.call(this, type, fn, opt);
    };
  }

  try { watchStockLogin(); patchExpireXhr(); } catch (e) {}

  window.FM = {
    USER: getUser(), login: login, ensure: ensure, relogin: relogin, get: get, post: post,
    forget: forget, hasCred: function () { return !!getPw(); },
    setCred: setPw
  };
})();
