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

  function initCollapse() {
    var sidebar = document.getElementById("admin-sidebar");
    var collapseBtn = document.querySelector("[data-collapse-sidebar]");
    if (!sidebar || !collapseBtn) return;

    var STORAGE_KEY = "admin-sidebar-collapsed";

    function setCollapsed(collapsed) {
      sidebar.classList.toggle("admin-sidebar--collapsed", collapsed);
      document.body.classList.toggle("admin-sidebar-collapsed", collapsed);
      collapseBtn.setAttribute("aria-label", collapsed ? "Laajenna valikko" : "Kutista valikko");
      try { localStorage.setItem(STORAGE_KEY, collapsed ? "1" : "0"); } catch (e) {}
    }

    // Restore state from localStorage
    try {
      if (localStorage.getItem(STORAGE_KEY) === "1") {
        setCollapsed(true);
      }
    } catch (e) {}

    collapseBtn.addEventListener("click", function () {
      setCollapsed(!sidebar.classList.contains("admin-sidebar--collapsed"));
    });

    // Tooltip on nav links when collapsed
    var tooltip = document.createElement("div");
    tooltip.className = "admin-sidebar-tooltip";
    document.body.appendChild(tooltip);

    document.querySelectorAll(".admin-nav-link").forEach(function (link) {
      link.addEventListener("mouseenter", function () {
        if (!sidebar.classList.contains("admin-sidebar--collapsed")) return;
        var textEl = link.querySelector(".admin-nav-text");
        if (!textEl) return;
        var rect = link.getBoundingClientRect();
        tooltip.textContent = textEl.textContent.trim();
        tooltip.style.top = Math.round(rect.top + (rect.height - 28) / 2) + "px";
        tooltip.style.left = Math.round(rect.right + 10) + "px";
        tooltip.style.display = "block";
      });
      link.addEventListener("mouseleave", function () {
        tooltip.style.display = "none";
      });
    });
  }

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

    initCollapse();

    var themeSelect = document.querySelector("[data-theme-select]");
    if (themeSelect && themeSelect.form) {
      themeSelect.addEventListener("change", function () {
        var theme = (themeSelect.value || "auto").toLowerCase();
        if (theme === "light" || theme === "dark") {
          document.documentElement.setAttribute("data-theme", theme);
        } else {
          document.documentElement.setAttribute("data-theme", "auto");
        }
        themeSelect.form.submit();
      });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
