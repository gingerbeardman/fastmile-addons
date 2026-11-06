// Headless harness: load the REAL client crypto stack + fm-auth.js in a
// browser-like context and drive it against the mock server. Validates the
// exact code the browser will run (login handshake, csrf, ddns r/w).
import fs from "node:fs";
import vm from "node:vm";
import path from "node:path";

const WWW = path.resolve("device/www");
const ASSETS = path.resolve("webui-dev/web_whw/assets/js");
const BASE = process.env.FM_HOST || "http://127.0.0.1:8080";

// minimal browser shims
function storage() {
  const m = new Map();
  return { getItem: k => (m.has(k) ? m.get(k) : null),
           setItem: (k, v) => m.set(k, String(v)),
           removeItem: k => m.delete(k), clear: () => m.clear() };
}
// route fetch's "/..." to the mock base, with a cookie jar (browsers have one)
const jar = new Map();
const wrappedFetch = async (u, o) => {
  o = o || {};
  const headers = new Headers(o.headers || {});
  if (jar.size)
    headers.set("Cookie", [...jar].map(([k, v]) => k + "=" + v).join("; "));
  const res = await fetch(u.startsWith("http") ? u : BASE + u,
                          { ...o, headers, redirect: "manual" });
  for (const c of res.headers.getSetCookie?.() || []) {
    const [kv] = c.split(";"); const i = kv.indexOf("=");
    if (i > 0) jar.set(kv.slice(0, i).trim(), kv.slice(i + 1).trim());
  }
  return res;
};

const sandbox = {
  window: {}, document: { getElementsByTagName: () => [] },
  sessionStorage: storage(), localStorage: storage(),
  fetch: wrappedFetch, console, navigator: { appName: "node" },
};
sandbox.window = sandbox;
sandbox.self = sandbox;
const ctx = vm.createContext(sandbox);

function run(file, dir) {
  const code = fs.readFileSync(path.join(dir, file), "utf8");
  vm.runInContext(code, ctx, { filename: file });
}

// load in the same order the page does
run("jsencrypt.min.js", ASSETS);
run("sjcl.js", ASSETS);
run("crypto_page.js", ASSETS);
run("fm-auth.js", WWW);

const FM = sandbox.FM;
if (!FM) { console.error("FAIL: window.FM not defined"); process.exit(1); }

function assert(cond, msg) {
  console.log((cond ? "  ok  " : "  FAIL") + "  " + msg);
  if (!cond) process.exitCode = 1;
}

const pw = process.env.MOCK_PW || "testpass";

(async () => {
  console.log("1) login with correct password");
  const ok = await FM.login(pw);
  assert(ok === true, "FM.login returns true");
  assert(!!sandbox.sessionStorage.getItem("token"), "csrf token stored");
  const sid = sandbox.sessionStorage.getItem("sid");
  assert(!!sid && !!sandbox.sessionStorage.getItem(sid),
         "AES key/iv stored under sid (stock-app compatible)");

  console.log("2) read current ddns config");
  let d = await (await FM.get("ddns_uci_web_app.cgi")).json();
  assert(d.service_name === "changeip.com", "default provider changeip.com");

  console.log("3) write ddns config via POST (+csrf)");
  let w = await (await FM.post("ddns_uci_web_app.cgi", {
    enabled: "1", service_name: "changeip.com",
    domain: "myhost.changeip.com", username: "user", password: "s3cret",
    interface: "wan" })).json();
  assert(w.result === 0, "save result 0");

  console.log("4) read back");
  d = await (await FM.get("ddns_uci_web_app.cgi")).json();
  assert(d.enabled === "1" && d.domain === "myhost.changeip.com" &&
         d.username === "user", "values persisted");
  assert(d.password === "", "password never echoed back to client");

  console.log("5) wrong password rejected");
  sandbox.sessionStorage.clear(); sandbox.localStorage.clear();
  const bad = await FM.login("nope-" + Math.random());
  assert(bad === false, "FM.login returns false for wrong pw");

  console.log("\n" + (process.exitCode ? "SOME CHECKS FAILED" : "ALL CHECKS PASSED"));
})();
