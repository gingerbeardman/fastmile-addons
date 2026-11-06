#!/bin/sh
# patch-index.sh — add the custom UI hooks to the router's own index.html.
# Run ON THE DEVICE as root (BusyBox ash/sed/awk is enough).
#
#   sh patch-index.sh [index.html]     default: /webs/web_whw/index.html
#
# The stock file is kept once as index.html.orig. Every run regenerates the
# patched file from that .orig, so running it again is safe and picks up new
# ?v= numbers. The patch:
#   - adds fm-theme.css and fm-theme.js before </head>
#   - adds jsencrypt.min.js, sjcl.js, crypto_page.js (if not already there)
#     and fm-auth.js before <app-root>
#   - adds fm-menu.js after </app-root>
#   - replaces the stock <script ... type="module"> tags with the
#     AUTO-LOGIN HOOK block, which logs in first (if a password is stored in
#     the browser) and then loads the same modules in order. The module file
#     names are read from the stock tags, so firmware with other hashes works.
#
# Cache busting: bump these when the files change (see docs/web-ui.md).
#   FM_THEME_CSS_V, FM_THEME_JS_V, FM_MENU_V, FM_MAIN_V (main.*.js; the
#   speed test fix patches that bundle, so browsers must refetch it).
#
# Revert: cp index.html.orig index.html

set -e
INDEX=${1:-/webs/web_whw/index.html}
ORIG=$INDEX.orig
FM_THEME_CSS_V=${FM_THEME_CSS_V:-12}
FM_THEME_JS_V=${FM_THEME_JS_V:-3}
FM_MENU_V=${FM_MENU_V:-9}
FM_MAIN_V=${FM_MAIN_V:-6}

[ -f "$INDEX" ] || { echo "missing $INDEX" >&2; exit 1; }

if [ ! -f "$ORIG" ]; then
  if grep -q 'fm-auth.js\|AUTO-LOGIN HOOK' "$INDEX"; then
    echo "$INDEX is already patched and there is no $ORIG to start from." >&2
    echo "Put the stock index.html back (or copy it to $ORIG) and run again." >&2
    exit 1
  fi
  cp -p "$INDEX" "$ORIG"
  echo "stock index saved as $ORIG"
fi

grep -q '<app-root' "$ORIG" || { echo "no <app-root> in $ORIG" >&2; exit 1; }
grep -q '</head>' "$ORIG" || { echo "no </head> in $ORIG" >&2; exit 1; }

# Module scripts in document order, e.g. runtime.<hash>.js polyfills... main...
MODS=$(awk '{
  line = $0
  while (match(line, /<script[^>]*type="module"[^>]*>/)) {
    tag = substr(line, RSTART, RLENGTH)
    line = substr(line, RSTART + RLENGTH)
    if (match(tag, /src="[^"]*"/)) print substr(tag, RSTART + 5, RLENGTH - 6)
  }
}' "$ORIG")
[ -n "$MODS" ] || { echo "no <script type=\"module\"> tags in $ORIG" >&2; exit 1; }

TMP=${TMPDIR:-/tmp}/fm-index.$$
HOOK=$TMP.hook
trap 'rm -f "$TMP" "$HOOK"' EXIT

# The hook block, with the module list filled in.
{
  echo '    <script src="fm-menu.js?v='"$FM_MENU_V"'"></script>'
  cat <<'EOF'
    <!-- AUTO-LOGIN HOOK: ensure a session, then boot Angular in order.
         If no stored credential (or login fails), Angular boots normally and
         shows its own login screen. Remove this block + restore the three
         original <script type="module"> tags to revert. -->
    <script>
    (function () {
EOF
  n=0
  for m in $MODS; do
    case "$m" in main.*) m="$m?v=$FM_MAIN_V" ;; esac
    if [ $n -eq 0 ]; then printf '      var mods = ["%s"' "$m"
    else printf ',\n                  "%s"' "$m"; fi
    n=$((n + 1))
  done
  printf '];\n'
  cat <<'EOF'
      function boot() {
        (function next(i) {
          if (i >= mods.length) return;
          var s = document.createElement("script");
          s.src = mods[i]; s.type = "module";
          s.onload = function () { next(i + 1); };
          s.onerror = function () { next(i + 1); };
          document.body.appendChild(s);
        })(0);
      }
      function keepalive() {
        // re-establish the session before it expires so the app never drops
        // back to the login screen (fm-auth re-logs-in if check_expire says so)
        if (window.FM && FM.hasCred())
          setInterval(function () { FM.ensure().catch(function () {}); },
                      5 * 60 * 1000);   // every 5 min (TTL is 15 min)
      }
      try {
        if (window.FM && FM.hasCred()) { FM.ensure().then(boot, boot); keepalive(); }
        else { boot(); }
      } catch (e) { boot(); }
    })();
    </script>
EOF
} > "$HOOK"

HAS_JSE=0; HAS_SJCL=0; HAS_CRYPTO=0
grep -q 'assets/js/jsencrypt.min.js' "$ORIG" && HAS_JSE=1
grep -q 'assets/js/sjcl.js' "$ORIG" && HAS_SJCL=1
grep -q 'assets/js/crypto_page.js' "$ORIG" && HAS_CRYPTO=1

awk -v hook="$HOOK" -v cssv="$FM_THEME_CSS_V" -v jsv="$FM_THEME_JS_V" \
    -v jse="$HAS_JSE" -v sjcl="$HAS_SJCL" -v cr="$HAS_CRYPTO" '
  {
    line = $0
    had_mod = 0
    while (match(line, /<script[^>]*type="module"[^>]*><\/script>/)) {
      line = substr(line, 1, RSTART - 1) substr(line, RSTART + RLENGTH)
      had_mod = 1
    }
    if (had_mod && line ~ /^[ \t]*$/) next

    if (!head_done && (i = index(line, "</head>"))) {
      line = substr(line, 1, i - 1) \
        "<link rel=\"stylesheet\" href=\"fm-theme.css?v=" cssv "\">" \
        "<script src=\"fm-theme.js?v=" jsv "\"></script>" substr(line, i)
      head_done = 1
    }

    if (!app_done && line ~ /<app-root/) {
      ind = line; sub(/<.*/, "", ind)
      if (!jse)  print ind "<script src=\"assets/js/jsencrypt.min.js\"></script>"
      if (!sjcl) print ind "<script src=\"assets/js/sjcl.js\"></script>"
      if (!cr)   print ind "<script src=\"assets/js/crypto_page.js\"></script>"
      print ind "<script src=\"fm-auth.js\"></script>"
      print line
      if (line ~ /<\/app-root>/) {
        while ((getline h < hook) > 0) print h
        close(hook)
        app_done = 1
      } else {
        app_open = 1
      }
      next
    }
    if (app_open && line ~ /<\/app-root>/) {
      print line
      while ((getline h < hook) > 0) print h
      close(hook)
      app_open = 0; app_done = 1
      next
    }
    print line
  }
  END { if (!head_done || !app_done) exit 1 }
' "$ORIG" > "$TMP"

grep -q 'fm-auth.js' "$TMP" && grep -q 'AUTO-LOGIN HOOK' "$TMP" \
  && grep -q 'fm-theme.css' "$TMP" || { echo "patch failed" >&2; exit 1; }
if grep -q 'type="module"></script>' "$TMP"; then
  echo "stock module tags still present; patch failed" >&2
  exit 1
fi

# cat > keeps the file's owner and mode.
cat "$TMP" > "$INDEX"
echo "patched $INDEX (modules: $(echo $MODS))"
