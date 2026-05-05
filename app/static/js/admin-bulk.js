(function () {
  "use strict";
  function initForm(form) {
    var bar = form.querySelector("[data-bulk-bar]");
    if (!bar) return;
    var submit = bar.querySelector("[data-bulk-submit]");
    var action = bar.querySelector("[data-bulk-action]");
    var checks = form.querySelectorAll("input[data-bulk-id]");
    var checkAll = form.querySelector("input[data-bulk-all]");

    function refresh() {
      var selected = form.querySelectorAll("input[data-bulk-id]:checked").length;
      bar.hidden = selected === 0;
    }
    checks.forEach(function (c) { c.addEventListener("change", refresh); });
    if (checkAll) {
      checkAll.addEventListener("change", function () {
        checks.forEach(function (c) { c.checked = checkAll.checked; });
        refresh();
      });
    }
    submit.addEventListener("click", function () {
      if (!action.value) return;
      form.submit();
    });
  }
  document.querySelectorAll("form[data-bulk-form]").forEach(initForm);
})();

