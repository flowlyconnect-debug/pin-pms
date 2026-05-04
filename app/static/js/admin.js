/* Admin UI behaviour — extracted from base.html so strict CSP (script-src 'self') applies.
 *
 * Handles:
 *   - Mobile sidebar toggle (.admin-menu-toggle, .admin-sidebar-backdrop)
 *   - Auto-close on link click on small viewports
 *   - Auto-close on viewport resize back to desktop
 *   - Esc key closes the sidebar
 *   - Clickable table rows with [data-href]
 */

(function () {
  "use strict";

  function init() {
    var toggle = document.querySelector(".admin-menu-toggle");
    var backdrop = document.querySelector(".admin-sidebar-backdrop");

    function setSidebarOpen(open) {
      document.body.classList.toggle("admin-sidebar-open", open);
      if (toggle) {
        toggle.setAttribute("aria-expanded", open ? "true" : "false");
        toggle.setAttribute("aria-label", open ? "Sulje valikko" : "Avaa valikko");
      }
    }

    if (toggle) {
      toggle.addEventListener("click", function () {
        setSidebarOpen(!document.body.classList.contains("admin-sidebar-open"));
      });
    }

    if (backdrop) {
      backdrop.addEventListener("click", function () {
        setSidebarOpen(false);
      });
    }

    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") {
        setSidebarOpen(false);
      }
    });

    window.addEventListener("resize", function () {
      if (window.matchMedia("(min-width: 901px)").matches) {
        setSidebarOpen(false);
      }
    });

    document.querySelectorAll(".admin-sidebar a").forEach(function (link) {
      link.addEventListener("click", function () {
        if (window.matchMedia("(max-width: 900px)").matches) {
          setSidebarOpen(false);
        }
      });
    });

    document.querySelectorAll("tr.table-row-link[data-href]").forEach(function (row) {
      row.addEventListener("click", function (ev) {
        if (ev.target.closest("a,button,input,select,textarea,label,form")) {
          return;
        }
        window.location.href = row.getAttribute("data-href");
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
