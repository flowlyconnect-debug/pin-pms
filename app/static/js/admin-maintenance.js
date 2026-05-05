(function () {
  "use strict";

  function init() {
    if (!window.AdminFormHelpers) {
      return;
    }
    var root = document.getElementById("maintenance-form-page");
    if (!root) {
      return;
    }
    window.AdminFormHelpers.initPropertyUnitFilter({
      propertySelectId: "property_id",
      unitSelectId: "unit_id",
      unitPropertyAttr: "data-property",
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
