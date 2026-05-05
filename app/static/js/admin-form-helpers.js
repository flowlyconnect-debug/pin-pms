(function () {
  "use strict";

  function initGuestSearch(options) {
    var searchEl = document.getElementById(options.searchInputId);
    var idEl = document.getElementById(options.hiddenIdInputId);
    var resultsEl = document.getElementById(options.resultsId);
    var clearBtn = document.getElementById(options.clearButtonId);
    var searchUrl = options.searchUrl || "";
    if (!searchEl || !idEl || !resultsEl || !searchUrl) {
      return;
    }
    var timer = null;

    function hideResults() {
      resultsEl.innerHTML = "";
      resultsEl.style.display = "none";
    }

    function labelForGuest(guest) {
      var name = (guest.name || guest.full_name || "").trim();
      var email = (guest.email || "").trim();
      if (name && email) {
        return name + " (" + email + ")";
      }
      return name || email || "Asiakas #" + String(guest.id);
    }

    function showPick(guest) {
      idEl.value = String(guest.id);
      searchEl.value = labelForGuest(guest);
      hideResults();
    }

    function render(list) {
      if (!list.length) {
        resultsEl.innerHTML = '<div class="guest-no-results">Asiakkaita ei löytynyt</div>';
        resultsEl.style.display = "block";
        return;
      }
      resultsEl.innerHTML = "";
      list.forEach(function (guest) {
        var label = labelForGuest(guest);
        if (!label.trim()) {
          return;
        }
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "guest-result";
        btn.textContent = label;
        btn.addEventListener("click", function () {
          showPick(guest);
        });
        resultsEl.appendChild(btn);
      });
      if (!resultsEl.children.length) {
        resultsEl.innerHTML = '<div class="guest-no-results">Asiakkaita ei löytynyt</div>';
      }
      resultsEl.style.display = "block";
    }

    function fetchGuests(query) {
      if (!String(query || "").trim()) {
        hideResults();
        return;
      }
      fetch(searchUrl + "?q=" + encodeURIComponent(query), { credentials: "same-origin" })
        .then(function (response) {
          return response.json();
        })
        .then(function (data) {
          render(Array.isArray(data) ? data : []);
        })
        .catch(function () {
          hideResults();
        });
    }

    searchEl.addEventListener("input", function () {
      clearTimeout(timer);
      var query = searchEl.value;
      timer = setTimeout(function () {
        fetchGuests(query);
      }, 200);
    });

    if (clearBtn) {
      clearBtn.addEventListener("click", function () {
        idEl.value = "";
        searchEl.value = "";
        hideResults();
      });
    }

    document.addEventListener("click", function (event) {
      var wrap = searchEl.closest(".guest-search-wrap");
      if (wrap && !wrap.contains(event.target)) {
        hideResults();
      }
    });
  }

  function initPropertyUnitFilter(options) {
    var propertyEl = document.getElementById(options.propertySelectId);
    var unitEl = document.getElementById(options.unitSelectId);
    var attrName = options.unitPropertyAttr || "data-property-id";
    if (!propertyEl || !unitEl) {
      return;
    }

    function runFilter() {
      var propertyId = String(propertyEl.value || "");
      var firstVisible = null;
      var selectedOption = unitEl.selectedOptions && unitEl.selectedOptions[0];
      var optionsList = unitEl.querySelectorAll("option");
      optionsList.forEach(function (option) {
        if (!option.value) {
          option.hidden = false;
          option.disabled = false;
          return;
        }
        var optionPropertyId = String(option.getAttribute(attrName) || "");
        var match = !propertyId || optionPropertyId === propertyId;
        option.hidden = !match;
        option.disabled = !match;
        if (match && !firstVisible) {
          firstVisible = option;
        }
      });

      if (selectedOption && selectedOption.disabled) {
        unitEl.value = firstVisible ? firstVisible.value : "";
      }
    }

    propertyEl.addEventListener("change", runFilter);
    runFilter();
  }

  window.AdminFormHelpers = {
    initGuestSearch: initGuestSearch,
    initPropertyUnitFilter: initPropertyUnitFilter,
  };
})();
