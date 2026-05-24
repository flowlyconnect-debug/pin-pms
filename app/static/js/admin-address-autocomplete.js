(function () {
  "use strict";

  var DEBOUNCE_MS = 300;
  var MIN_QUERY_LEN = 3;

  function initForm(form) {
    if (!form || form.dataset.addressAutocompleteInit === "1") {
      return;
    }
    var addressInput = form.querySelector("#address");
    if (!addressInput) {
      return;
    }
    form.dataset.addressAutocompleteInit = "1";

    var suggestUrl = form.getAttribute("data-address-suggest-url");
    if (!suggestUrl) {
      return;
    }

    var streetInput = form.querySelector("#street_address");
    var postalInput = form.querySelector("#postal_code");
    var cityInput = form.querySelector("#city");
    var latInput = form.querySelector("#latitude");
    var lonInput = form.querySelector("#longitude");

    var wrap = document.createElement("div");
    wrap.className = "address-suggest-wrap";
    addressInput.parentNode.insertBefore(wrap, addressInput);
    wrap.appendChild(addressInput);

    var list = document.createElement("div");
    list.className = "address-suggest-results";
    list.hidden = true;
    list.setAttribute("role", "listbox");
    list.id = "address_suggest_results";
    wrap.appendChild(list);

    var timer = null;
    var activeController = null;
    var items = [];

    function hideList() {
      list.hidden = true;
      list.innerHTML = "";
      items = [];
    }

    function applySelection(item) {
      if (streetInput && item.street) {
        streetInput.value = item.street;
      }
      if (postalInput && item.postal_code) {
        postalInput.value = item.postal_code;
      }
      if (cityInput && item.city) {
        cityInput.value = item.city;
      }
      if (item.label) {
        addressInput.value = item.label;
      }
      if (latInput && item.lat != null && item.lat !== "") {
        latInput.value = String(item.lat);
      }
      if (lonInput && item.lon != null && item.lon !== "") {
        lonInput.value = String(item.lon);
      }
      hideList();
    }

    function render() {
      list.innerHTML = "";
      if (!items.length) {
        hideList();
        return;
      }
      items.forEach(function (item, index) {
        var button = document.createElement("button");
        button.type = "button";
        button.className = "address-suggest-item";
        button.textContent = item.label || item.street || "";
        button.setAttribute("role", "option");
        button.id = "address-suggest-opt-" + index;
        button.addEventListener("mousedown", function (ev) {
          ev.preventDefault();
        });
        button.addEventListener("click", function () {
          applySelection(item);
        });
        list.appendChild(button);
      });
      list.hidden = false;
    }

    async function fetchSuggestions() {
      var q = (addressInput.value || "").trim();
      if (q.length < MIN_QUERY_LEN) {
        hideList();
        return;
      }
      if (activeController) {
        activeController.abort();
      }
      activeController = new AbortController();
      try {
        var url =
          suggestUrl +
          (suggestUrl.indexOf("?") >= 0 ? "&" : "?") +
          "q=" +
          encodeURIComponent(q);
        var res = await fetch(url, {
          credentials: "same-origin",
          signal: activeController.signal,
        });
        if (!res.ok) {
          hideList();
          return;
        }
        var body = await res.json();
        items = body && body.success && Array.isArray(body.data) ? body.data : [];
        render();
      } catch (err) {
        if (err && err.name === "AbortError") {
          return;
        }
        hideList();
      }
    }

    addressInput.addEventListener("input", function () {
      window.clearTimeout(timer);
      timer = window.setTimeout(fetchSuggestions, DEBOUNCE_MS);
    });

    addressInput.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") {
        hideList();
      }
      if (ev.key === "Enter" && !list.hidden && items.length) {
        ev.preventDefault();
        applySelection(items[0]);
      }
    });

    document.addEventListener("click", function (ev) {
      if (!wrap.contains(ev.target)) {
        hideList();
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("form[data-address-autocomplete]").forEach(initForm);
  });
})();
