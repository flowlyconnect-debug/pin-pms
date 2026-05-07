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
    initOrgSwitcher();
    initTooltips();
    initConflictsUi();
    initMobileMoreSheet();
    initSidebarNavTooltips();
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

  function initSidebarNavTooltips() {
    document.querySelectorAll(".admin-nav-link").forEach(function (link) {
      var label = link.querySelector(".admin-nav-text");
      if (!label) return;
      var text = (label.textContent || "").trim();
      if (!text) return;
      link.setAttribute("data-tooltip", text);
      link.setAttribute("title", text);
    });
  }

  function initMobileMoreSheet() {
    var sheet = document.querySelector("[data-mobile-more-sheet]");
    var openTrigger = document.querySelector("[data-mobile-more-open]");
    if (!sheet || !openTrigger) return;

    function setOpen(open) {
      sheet.hidden = !open;
      document.body.classList.toggle("admin-mobile-sheet-open", open);
    }

    openTrigger.addEventListener("click", function () {
      setOpen(true);
    });

    sheet.querySelectorAll("[data-mobile-more-close]").forEach(function (closeButton) {
      closeButton.addEventListener("click", function () {
        setOpen(false);
      });
    });

    sheet.querySelectorAll("a").forEach(function (link) {
      link.addEventListener("click", function () {
        setOpen(false);
      });
    });

    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") {
        setOpen(false);
      }
    });
  }

  function initOrgSwitcher() {
    var switcherRoot = document.querySelector("[data-org-switcher]");
    if (!switcherRoot) return;

    var storageKey = "pin-pms-active-org";
    var currentOrgId = Number(switcherRoot.getAttribute("data-current-org-id") || 0) || null;
    var currentOrgName = (switcherRoot.getAttribute("data-current-org-name") || "Flowly").trim() || "Flowly";
    var savedRaw = localStorage.getItem(storageKey);
    var savedOrg = null;
    if (savedRaw) {
      try {
        savedOrg = JSON.parse(savedRaw);
      } catch (_err) {
        savedOrg = null;
      }
    }

    var defaultOrg = {
      id: currentOrgId || 1,
      name: currentOrgName,
      plan: "Pro",
    };
    var orgs = [defaultOrg];
    var activeOrg = savedOrg && Number(savedOrg.id) ? savedOrg : defaultOrg;

    function hueFromOrg(name) {
      var input = (name || "Flowly").toLowerCase();
      var hash = 0;
      for (var i = 0; i < input.length; i += 1) {
        hash = (hash << 5) - hash + input.charCodeAt(i);
        hash |= 0;
      }
      return Math.abs(hash) % 360;
    }

    function initialsFromOrg(name) {
      var trimmed = (name || "").trim();
      if (!trimmed) return "OR";
      var parts = trimmed.split(/\s+/).filter(Boolean);
      if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
      return (parts[0].charAt(0) + parts[parts.length - 1].charAt(0)).toUpperCase();
    }

    function persist(org) {
      activeOrg = org;
      localStorage.setItem(storageKey, JSON.stringify(org));
      window.PinPmsOrgContext = {
        activeOrg: activeOrg,
        orgs: orgs.slice(),
        setActiveOrg: function (nextOrg) {
          persist(nextOrg);
          render();
        },
      };
    }

    var outsideClickBound = false;

    function render() {
      if (!orgs.length) return;
      var hasDropdown = orgs.length > 1;
      var active = orgs.find(function (item) { return Number(item.id) === Number(activeOrg.id); }) || orgs[0];
      var itemRows = orgs.map(function (org) {
        var isActive = Number(org.id) === Number(active.id);
        return (
          '<button type="button" class="admin-org-switcher-item" data-org-id="' + String(org.id) + '">' +
            '<span class="admin-org-switcher-item-name">' + escapeHtml(org.name) + '</span>' +
            '<span class="admin-org-switcher-item-check" aria-hidden="true">' + (isActive ? "✓" : "") + "</span>" +
          "</button>"
        );
      }).join("");

      switcherRoot.style.setProperty("--org-hue", String(hueFromOrg(active.name)));
      switcherRoot.innerHTML =
        '<button type="button" class="admin-org-switcher-trigger" ' +
          (hasDropdown ? 'aria-haspopup="menu" aria-expanded="false"' : "disabled") + ">" +
          '<span class="admin-org-switcher-avatar" aria-hidden="true">' + initialsFromOrg(active.name) + "</span>" +
          '<span class="admin-org-switcher-name">' + escapeHtml(active.name) + "</span>" +
          (hasDropdown ? '<span class="admin-org-switcher-chevron" aria-hidden="true">⇅</span>' : "") +
        "</button>" +
        (hasDropdown
          ? '<div class="admin-org-switcher-menu" role="menu" hidden>' +
              '<p class="admin-org-switcher-label">Vaihda organisaatiota</p>' +
              itemRows +
            "</div>"
          : "");

      var trigger = switcherRoot.querySelector(".admin-org-switcher-trigger");
      var menu = switcherRoot.querySelector(".admin-org-switcher-menu");

      if (trigger && menu) {
        trigger.addEventListener("click", function () {
          var open = trigger.getAttribute("aria-expanded") === "true";
          trigger.setAttribute("aria-expanded", open ? "false" : "true");
          menu.hidden = open;
        });

        switcherRoot.querySelectorAll("[data-org-id]").forEach(function (button) {
          button.addEventListener("click", function () {
            var selectedId = Number(button.getAttribute("data-org-id"));
            var next = orgs.find(function (org) { return Number(org.id) === selectedId; });
            if (!next) return;
            persist(next);
            render();
          });
        });

        if (!outsideClickBound) {
          document.addEventListener("click", function (event) {
            var openTrigger = switcherRoot.querySelector(".admin-org-switcher-trigger");
            var openMenu = switcherRoot.querySelector(".admin-org-switcher-menu");
            if (!openTrigger || !openMenu) return;
            if (!switcherRoot.contains(event.target)) {
              openTrigger.setAttribute("aria-expanded", "false");
              openMenu.hidden = true;
            }
          });
          outsideClickBound = true;
        }
      }
    }

    function escapeHtml(value) {
      return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
    }

    function syncFromApiOrFallback() {
      return fetch("/api/organizations", {
        headers: { Accept: "application/json" },
        credentials: "same-origin",
      })
        .then(function (res) {
          if (!res.ok) throw new Error("organizations endpoint unavailable");
          return res.json();
        })
        .then(function (data) {
          var list = Array.isArray(data) ? data : (Array.isArray(data.organizations) ? data.organizations : []);
          if (!list.length) throw new Error("empty organizations payload");
          orgs = list.map(function (org) {
            return {
              id: Number(org.id) || 0,
              name: String(org.name || "Organisaatio"),
              plan: String(org.plan || ""),
            };
          }).filter(function (org) { return org.id > 0; });
        })
        .catch(function () {
          orgs = [{ id: 1, name: "Flowly", plan: "Pro" }];
        })
        .finally(function () {
          var nextActive = orgs.find(function (org) { return Number(org.id) === Number(activeOrg.id); }) || orgs[0];
          persist(nextActive);
          render();
        });
    }

    syncFromApiOrFallback();
  }

  function initConflictsUi() {
    fetch("/api/conflicts", {
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    })
      .then(function (res) {
        if (!res.ok) throw new Error("conflicts endpoint unavailable");
        return res.json();
      })
      .then(function (payload) {
        var count = Number(payload && payload.count) || 0;
        var navBadge = document.querySelector("[data-conflicts-nav-badge]");
        if (navBadge) {
          navBadge.textContent = String(count);
          navBadge.hidden = count <= 0;
          navBadge.setAttribute("aria-label", count + " konfliktia");
        }

        var banner = document.querySelector("[data-conflicts-banner]");
        var bannerText = document.querySelector("[data-conflicts-banner-text]");
        if (banner && bannerText) {
          if (count > 0) {
            banner.hidden = false;
            bannerText.textContent = "Sinulla on " + count + " konfliktia jotka vaativat huomiota";
          } else {
            banner.hidden = true;
          }
        }
      })
      .catch(function () {
        // Keep UI silent when endpoint is unavailable.
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
