(function () {
  "use strict";

  function revealTableShell(shell) {
    var skeleton = shell.querySelector("[data-table-skeleton]");
    var content = shell.querySelector("[data-table-content]");
    if (!skeleton || !content) {
      return;
    }
    content.hidden = false;
    skeleton.hidden = true;
  }

  function init() {
    var shells = document.querySelectorAll("[data-table-load-shell]");
    if (!shells.length) {
      return;
    }
    window.requestAnimationFrame(function () {
      shells.forEach(revealTableShell);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
