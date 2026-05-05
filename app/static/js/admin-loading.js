(function () {
  "use strict";

  var overlayEl = null;

  function createOverlay(message) {
    var overlay = document.createElement("div");
    overlay.className = "admin-loading-overlay";
    overlay.setAttribute("role", "status");
    overlay.setAttribute("aria-live", "polite");
    overlay.setAttribute("aria-label", "Ladataan");
    overlay.setAttribute("aria-busy", "true");

    var box = document.createElement("div");
    box.className = "admin-loading-box";

    var spinner = document.createElement("span");
    spinner.className = "admin-loading-spinner";
    spinner.setAttribute("aria-hidden", "true");

    var text = document.createElement("span");
    text.className = "admin-loading-text";
    text.textContent = message || "Ladataan…";

    box.appendChild(spinner);
    box.appendChild(text);
    overlay.appendChild(box);
    return overlay;
  }

  function show(message) {
    if (overlayEl && document.body.contains(overlayEl)) {
      var textEl = overlayEl.querySelector(".admin-loading-text");
      if (textEl) {
        textEl.textContent = message || "Ladataan…";
      }
      return;
    }
    overlayEl = createOverlay(message);
    document.body.appendChild(overlayEl);
    document.body.setAttribute("aria-busy", "true");
  }

  function hide() {
    if (overlayEl && overlayEl.parentNode) {
      overlayEl.parentNode.removeChild(overlayEl);
    }
    overlayEl = null;
    document.body.removeAttribute("aria-busy");
  }

  function setButtonLoading(button) {
    if (!button || button.dataset.loadingDone === "1") {
      return;
    }
    button.dataset.loadingDone = "1";
    button.dataset.loadingOriginalText = button.textContent || "";
    button.disabled = true;
    button.classList.add("is-loading");
    button.textContent = "";
    var spinner = document.createElement("span");
    spinner.className = "btn-loading-spinner";
    spinner.setAttribute("aria-hidden", "true");
    var label = document.createElement("span");
    label.className = "btn-loading-label";
    label.textContent = button.dataset.loadingOriginalText;
    button.appendChild(spinner);
    button.appendChild(label);
  }

  function wireLoadingButtons() {
    document.querySelectorAll("button[data-loading-button], input[type='submit'][data-loading-button]").forEach(
      function (button) {
        button.addEventListener("click", function () {
          setButtonLoading(button);
        });
      }
    );
  }

  function wireLoadingForms() {
    document.querySelectorAll("form[data-loading]").forEach(function (form) {
      form.addEventListener("submit", function () {
        var submitter = form.querySelector("[data-loading-button]:focus");
        if (submitter) {
          setButtonLoading(submitter);
        }
        show(form.dataset.loading || "Tallennetaan…");
      });
    });
  }

  window.loading = { show: show, hide: hide };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      wireLoadingButtons();
      wireLoadingForms();
    });
  } else {
    wireLoadingButtons();
    wireLoadingForms();
  }
})();
