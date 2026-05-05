(function () {
  "use strict";

  var dialogCounter = 0;

  function confirmAction(options) {
    var opts = options || {};
    var title = opts.title || "Vahvista toiminto";
    var message = opts.message || "Haluatko varmasti jatkaa?";
    var confirmLabel = opts.confirmLabel || "Vahvista";
    var cancelLabel = opts.cancelLabel || "Peruuta";
    var dangerous = !!opts.dangerous;
    var previouslyFocused = document.activeElement;

    if (typeof HTMLDialogElement === "undefined") {
      return Promise.resolve(true);
    }

    return new Promise(function (resolve) {
      var dialog = document.createElement("dialog");
      dialog.className = "admin-confirm-dialog";
      dialogCounter += 1;
      var titleId = "admin-confirm-title-" + String(dialogCounter);
      dialog.setAttribute("aria-labelledby", titleId);

      var content = document.createElement("div");
      content.className = "admin-confirm-content";

      var titleEl = document.createElement("h2");
      titleEl.id = titleId;
      titleEl.className = "admin-confirm-title";
      titleEl.textContent = title;

      var messageEl = document.createElement("p");
      messageEl.className = "admin-confirm-message";
      messageEl.textContent = message;

      var actions = document.createElement("div");
      actions.className = "admin-confirm-actions";

      var cancelBtn = document.createElement("button");
      cancelBtn.type = "button";
      cancelBtn.className = "btn btn-secondary";
      cancelBtn.setAttribute("data-cancel", "1");
      cancelBtn.textContent = cancelLabel;

      var confirmBtn = document.createElement("button");
      confirmBtn.type = "button";
      confirmBtn.className = dangerous ? "btn btn-danger" : "btn btn-primary";
      confirmBtn.setAttribute("data-confirm", "1");
      confirmBtn.textContent = confirmLabel;

      actions.appendChild(cancelBtn);
      actions.appendChild(confirmBtn);
      content.appendChild(titleEl);
      content.appendChild(messageEl);
      content.appendChild(actions);
      dialog.appendChild(content);

      function cleanup(result) {
        if (dialog.open) {
          dialog.close();
        }
        dialog.remove();
        if (previouslyFocused && typeof previouslyFocused.focus === "function") {
          previouslyFocused.focus();
        }
        resolve(result);
      }

      function trapFocus(event) {
        if (event.key !== "Tab") {
          return;
        }
        var focusables = dialog.querySelectorAll(
          'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
        );
        if (!focusables.length) {
          event.preventDefault();
          return;
        }
        var first = focusables[0];
        var last = focusables[focusables.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }

      dialog.addEventListener("cancel", function (event) {
        event.preventDefault();
        cleanup(false);
      });

      dialog.addEventListener("keydown", trapFocus);
      cancelBtn.addEventListener("click", function () {
        cleanup(false);
      });
      confirmBtn.addEventListener("click", function () {
        cleanup(true);
      });

      document.body.appendChild(dialog);
      dialog.showModal();
      confirmBtn.focus();
    });
  }

  function bindDataConfirmForms() {
    document.querySelectorAll("form[data-confirm]").forEach(function (form) {
      form.addEventListener("submit", function (event) {
        if (form.dataset.confirmHandled === "1") {
          return;
        }
        event.preventDefault();
        var config = {};
        try {
          config = JSON.parse(form.dataset.confirm || "{}");
        } catch (_error) {
          config = { message: "Haluatko varmasti jatkaa?" };
        }
        confirmAction(config).then(function (ok) {
          if (!ok) {
            return;
          }
          form.dataset.confirmHandled = "1";
          if (typeof form.requestSubmit === "function") {
            form.requestSubmit();
          } else {
            form.submit();
          }
        });
      });
    });
  }

  window.confirmAction = confirmAction;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bindDataConfirmForms);
  } else {
    bindDataConfirmForms();
  }
})();
