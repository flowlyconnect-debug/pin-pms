(function () {
  "use strict";

  var ICONS = {
    success: "✓",
    warning: "!",
    error: "×",
    info: "i",
  };

  var DURATIONS = {
    success: 5000,
    info: 5000,
    warning: 8000,
    error: 0,
  };

  var stackEl = null;

  function ensureStack() {
    if (stackEl && document.body.contains(stackEl)) {
      return stackEl;
    }
    stackEl = document.createElement("div");
    stackEl.className = "toast-stack";
    stackEl.setAttribute("aria-label", "Ilmoitukset");
    document.body.appendChild(stackEl);
    return stackEl;
  }

  function removeToast(toastEl) {
    if (!toastEl || toastEl.dataset.closing === "1") {
      return;
    }
    toastEl.dataset.closing = "1";
    toastEl.classList.add("is-closing");
    window.setTimeout(function () {
      if (toastEl.parentNode) {
        toastEl.parentNode.removeChild(toastEl);
      }
    }, 220);
  }

  function showToast(level, message, options) {
    if (!message) {
      return null;
    }
    var opts = options || {};
    var toastEl = document.createElement("div");
    toastEl.className = "toast toast-" + level;
    toastEl.setAttribute("role", "status");
    toastEl.setAttribute("aria-live", level === "warning" || level === "error" ? "assertive" : "polite");

    var iconEl = document.createElement("span");
    iconEl.className = "toast-icon";
    iconEl.setAttribute("aria-hidden", "true");
    iconEl.textContent = ICONS[level] || ICONS.info;

    var messageEl = document.createElement("div");
    messageEl.className = "toast-message";
    messageEl.textContent = String(message);

    var closeEl = document.createElement("button");
    closeEl.type = "button";
    closeEl.className = "toast-close";
    closeEl.setAttribute("aria-label", "Sulje ilmoitus");
    closeEl.textContent = "×";
    closeEl.addEventListener("click", function () {
      removeToast(toastEl);
    });

    toastEl.appendChild(iconEl);
    toastEl.appendChild(messageEl);
    toastEl.appendChild(closeEl);
    ensureStack().appendChild(toastEl);

    window.requestAnimationFrame(function () {
      toastEl.classList.add("is-visible");
    });

    var duration = typeof opts.duration === "number" ? opts.duration : DURATIONS[level];
    if (duration > 0) {
      window.setTimeout(function () {
        removeToast(toastEl);
      }, duration);
    }
    return toastEl;
  }

  function flashCategoryToLevel(category) {
    var normalized = String(category || "").toLowerCase();
    if (normalized === "success") {
      return "success";
    }
    if (normalized === "warning") {
      return "warning";
    }
    if (normalized === "error" || normalized === "danger") {
      return "error";
    }
    return "info";
  }

  function consumeFlaskFlashData() {
    var source = document.getElementById("flash-toast-data");
    if (!source) {
      return;
    }
    var items = source.querySelectorAll("[data-flash-message]");
    items.forEach(function (item) {
      var category = item.getAttribute("data-flash-category");
      var message = item.getAttribute("data-flash-message");
      showToast(flashCategoryToLevel(category), message);
    });
  }

  window.toast = {
    success: function (message, options) {
      return showToast("success", message, options);
    },
    warning: function (message, options) {
      return showToast("warning", message, options);
    },
    error: function (message, options) {
      return showToast("error", message, options);
    },
    info: function (message, options) {
      return showToast("info", message, options);
    },
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", consumeFlaskFlashData);
  } else {
    consumeFlaskFlashData();
  }
})();
