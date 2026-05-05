(function () {
  "use strict";

  function qs(root, selector) {
    return root ? root.querySelector(selector) : null;
  }

  function renderUnreadList(listEl, items) {
    if (!listEl) {
      return;
    }
    listEl.innerHTML = "";
    if (!items.length) {
      var empty = document.createElement("li");
      empty.className = "admin-notifications-empty";
      empty.textContent = "Ei lukemattomia ilmoituksia.";
      listEl.appendChild(empty);
      return;
    }
    items.forEach(function (item) {
      var li = document.createElement("li");
      li.className = "admin-notification-item";
      var link = document.createElement("a");
      link.href = item.link || "/admin/notifications";
      link.textContent = item.title || "Ilmoitus";
      li.appendChild(link);
      if (item.body) {
        var body = document.createElement("div");
        body.className = "meta";
        body.textContent = item.body;
        li.appendChild(body);
      }
      listEl.appendChild(li);
    });
  }

  function init() {
    var wrapper = document.querySelector("[data-admin-notifications]");
    if (!wrapper) {
      return;
    }
    var toggle = qs(wrapper, "[data-notifications-toggle]");
    var panel = qs(wrapper, "[data-notifications-panel]");
    var badge = qs(wrapper, "[data-notifications-badge]");
    var listEl = qs(wrapper, "[data-notifications-list]");

    function setOpen(open) {
      if (!panel || !toggle) {
        return;
      }
      panel.hidden = !open;
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    }

    function refreshCount() {
      fetch("/admin/notifications/unread_count", { credentials: "same-origin" })
        .then(function (response) { return response.json(); })
        .then(function (payload) {
          var count = Number(payload.count || 0);
          if (!badge) {
            return;
          }
          badge.hidden = count <= 0;
          badge.textContent = String(count);
        })
        .catch(function () {});
    }

    function refreshList() {
      fetch("/admin/notifications/unread", { credentials: "same-origin" })
        .then(function (response) { return response.json(); })
        .then(function (payload) {
          renderUnreadList(listEl, Array.isArray(payload.items) ? payload.items : []);
        })
        .catch(function () {});
    }

    if (toggle) {
      toggle.addEventListener("click", function () {
        var opening = panel && panel.hidden;
        setOpen(Boolean(opening));
        if (opening) {
          refreshList();
        }
      });
    }
    document.addEventListener("click", function (event) {
      if (!wrapper.contains(event.target)) {
        setOpen(false);
      }
    });

    refreshCount();
    window.setInterval(refreshCount, 30000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
