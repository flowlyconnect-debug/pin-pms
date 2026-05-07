(function () {
  "use strict";
  var palette = document.getElementById("admin-command-palette");
  var openButtons = document.querySelectorAll("[data-command-open]");
  var closeButtons = document.querySelectorAll("[data-command-close]");
  var kbdHints = document.querySelectorAll("[data-kbd-hint]");
  var input = document.getElementById("admin-global-search");
  var list = document.getElementById("admin-global-search-results");
  if (!palette || !input || !list) return;

  var isMac = /Mac|iPhone|iPad|iPod/i.test(window.navigator.platform || "");
  kbdHints.forEach(function (node) {
    node.textContent = isMac ? "⌘K" : "Ctrl K";
  });

  function openPalette() {
    palette.hidden = false;
    window.setTimeout(function () {
      input.focus();
    }, 0);
  }

  function closePalette() {
    palette.hidden = true;
    items = [];
    render();
  }

  openButtons.forEach(function (button) {
    button.addEventListener("click", openPalette);
  });
  closeButtons.forEach(function (button) {
    button.addEventListener("click", closePalette);
  });

  document.addEventListener("keydown", function (ev) {
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "k") {
      ev.preventDefault();
      openPalette();
      return;
    }
    if (ev.key === "Escape" && !palette.hidden) {
      ev.preventDefault();
      closePalette();
    }
  });
  var timer = null;
  var items = [];

  function render() {
    list.innerHTML = "";
    if (!items.length) {
      list.hidden = true;
      return;
    }
    items.forEach(function (item, index) {
      var el = document.createElement("a");
      el.href = item.url;
      el.textContent = item.label + (item.sublabel ? " - " + item.sublabel : "");
      el.setAttribute("role", "option");
      el.id = "admin-search-opt-" + index;
      list.appendChild(el);
    });
    list.hidden = false;
  }

  async function searchNow() {
    var q = (input.value || "").trim();
    if (q.length < 2) {
      items = [];
      render();
      return;
    }
    var res = await fetch("/admin/search?q=" + encodeURIComponent(q), { credentials: "same-origin" });
    var body = await res.json();
    items = body && body.data ? body.data : [];
    render();
  }

  input.addEventListener("input", function () {
    window.clearTimeout(timer);
    timer = window.setTimeout(searchNow, 200);
  });
  input.addEventListener("keydown", function (ev) {
    if (ev.key === "Enter" && items.length) window.location.href = items[0].url;
    if (ev.key === "Escape") {
      closePalette();
    }
  });
})();

