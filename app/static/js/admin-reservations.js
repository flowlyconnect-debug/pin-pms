(function () {
  "use strict";

  function init() {
    if (!window.AdminFormHelpers) {
      return;
    }
    var root = document.getElementById("reservation-form-page");
    if (!root) {
      return;
    }

    if (root.dataset.hasPropertyFilter === "1") {
      window.AdminFormHelpers.initPropertyUnitFilter({
        propertySelectId: "property_id",
        unitSelectId: "unit_id",
        unitPropertyAttr: "data-property-id",
      });
    }

    var searchUrl = root.dataset.guestSearchUrl || "";
    window.AdminFormHelpers.initGuestSearch({
      searchInputId: "guest_search",
      hiddenIdInputId: "guest_id",
      resultsId: "guest_search_results",
      clearButtonId: "guest_search_clear",
      searchUrl: searchUrl,
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
