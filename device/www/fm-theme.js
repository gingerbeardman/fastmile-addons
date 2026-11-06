/* fm-theme.js — follow the operating system's light or dark theme. */
(function () {
  var mq = window.matchMedia("(prefers-color-scheme: dark)");

  function apply() {
    document.documentElement.classList.toggle("fm-dark", mq.matches);
  }

  apply();
  if (mq.addEventListener) mq.addEventListener("change", apply);
  else if (mq.addListener) mq.addListener(apply);
})();
