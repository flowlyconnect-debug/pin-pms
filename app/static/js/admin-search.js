(function () {
  "use strict";
  var input = document.getElementById("admin-global-search");
  var list = document.getElementById("admin-global-search-results");
  if (!input || !list) return;
  var timer = null;
  var items = [];

  function render() {
    list.innerHTML = "";
    if (!items.length) {
      list.hidden = true;
      input.setAttribute("aria-expanded", "false");
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
    input.setAttribute("aria-expanded", "true");
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
      items = [];
      render();
    }
  });
  document.addEventListener("keydown", function (ev) {
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "k") {
      ev.preventDefault();
      input.focus();
    }
  });
})();

