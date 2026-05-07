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

    document.querySelectorAll("[data-theme-select]").forEach(function (themeSelect) {
      if (!themeSelect.form) return;
      themeSelect.addEventListener("change", function () {
        var theme = (themeSelect.value || "auto").toLowerCase();
        if (theme === "light" || theme === "dark") {
          document.documentElement.setAttribute("data-theme", theme);
        } else {
          document.documentElement.setAttribute("data-theme", "auto");
        }
        themeSelect.form.submit();
      });
    });

    initAvatars();
    initTooltips();
  }

  function initialsFromName(name) {
    var trimmed = (name || "").trim();
    if (!trimmed) return "PM";
    var parts = trimmed.split(/\s+/).filter(Boolean);
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0].charAt(0) + parts[parts.length - 1].charAt(0)).toUpperCase();
  }

  function hueFromName(name) {
    var input = (name || "PM").toLowerCase();
    var hash = 0;
    for (var i = 0; i < input.length; i += 1) {
      hash = (hash << 5) - hash + input.charCodeAt(i);
      hash |= 0;
    }
    return Math.abs(hash) % 360;
  }

  function initAvatars() {
    document.querySelectorAll("[data-avatar]").forEach(function (avatar) {
      var name = avatar.getAttribute("data-avatar-name") || "Pindora";
      var src = (avatar.getAttribute("data-avatar-src") || "").trim();
      var initialsNode = avatar.querySelector(".admin-avatar__initials");
      var imageNode = avatar.querySelector(".admin-avatar__img");
      var initials = initialsFromName(name);

      if (initialsNode) initialsNode.textContent = initials;
      avatar.style.setProperty("--avatar-hue", String(hueFromName(name)));

      if (imageNode && src) {
        imageNode.src = src;
        imageNode.hidden = false;
        avatar.classList.add("has-image");
      } else if (imageNode) {
        imageNode.hidden = true;
        avatar.classList.remove("has-image");
      }
    });
  }

  function initTooltips() {
    var activeTooltipTarget = null;

    function showTooltip(target) {
      var text = target.getAttribute("data-tooltip");
      if (!text) return;
      target.classList.add("tooltip-visible");
      activeTooltipTarget = target;
    }

    function hideTooltip(target) {
      target.classList.remove("tooltip-visible");
      if (activeTooltipTarget === target) activeTooltipTarget = null;
    }

    document.querySelectorAll("[data-tooltip]").forEach(function (target) {
      target.addEventListener("mouseenter", function () { showTooltip(target); });
      target.addEventListener("mouseleave", function () { hideTooltip(target); });
      target.addEventListener("focus", function () { showTooltip(target); });
      target.addEventListener("blur", function () { hideTooltip(target); });
    });

    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && activeTooltipTarget) {
        hideTooltip(activeTooltipTarget);
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
