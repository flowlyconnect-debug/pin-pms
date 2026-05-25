(function () {
  "use strict";

  var DEBOUNCE_MS = 300;
  var MIN_QUERY_LEN = 3;

  function debugLog(form, message, detail) {
    if (!form || form.getAttribute("data-address-debug") !== "1") {
      return;
    }
    if (typeof console !== "undefined" && console.debug) {
      console.debug("[address-suggest] " + message, detail || "");
    }
  }

  function resolveSuggestInput(form) {
    var inputId = (form.getAttribute("data-address-input") || "street_address").trim();
    if (!inputId) {
      return null;
    }
    return form.querySelector("#" + CSS.escape(inputId));
  }

  function initForm(form) {
    if (!form || form.dataset.addressAutocompleteInit === "1") {
      return;
    }

    var suggestInput = resolveSuggestInput(form);
    if (!suggestInput) {
      return;
    }

    var suggestUrl = form.getAttribute("data-address-suggest-url");
    if (!suggestUrl) {
      return;
    }

    form.dataset.addressAutocompleteInit = "1";

    var streetInput = form.querySelector("#street_address");
    var postalInput = form.querySelector("#postal_code");
    var cityInput = form.querySelector("#city");
    var addressInput = form.querySelector("#address");
    var latInput = form.querySelector("#latitude");
    var lonInput = form.querySelector("#longitude");

    var wrap = document.createElement("div");
    wrap.className = "address-suggest-wrap";
    suggestInput.parentNode.insertBefore(wrap, suggestInput);
    wrap.appendChild(suggestInput);

    var list = document.createElement("div");
    list.className = "address-suggest-results";
    list.setAttribute("role", "listbox");
    list.id = suggestInput.id + "_suggest_results";
    list.style.display = "none";
    wrap.appendChild(list);

    var timer = null;
    var activeController = null;
    var items = [];

    function hideList() {
      list.style.display = "none";
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
      if (addressInput && item.label) {
        addressInput.value = item.label;
      } else if (item.label) {
        suggestInput.value = item.label;
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
        button.id = suggestInput.id + "-suggest-opt-" + index;
        button.addEventListener("mousedown", function (ev) {
          ev.preventDefault();
        });
        button.addEventListener("click", function () {
          applySelection(item);
        });
        list.appendChild(button);
      });
      list.style.display = "block";
    }

    async function fetchSuggestions() {
      var q = (suggestInput.value || "").trim();
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
        debugLog(form, "fetch", url);
        var res = await fetch(url, {
          credentials: "same-origin",
          signal: activeController.signal,
          headers: { Accept: "application/json" },
        });
        if (!res.ok) {
          debugLog(form, "http error", res.status);
          hideList();
          return;
        }
        var body = await res.json();
        items =
          body && body.success && Array.isArray(body.data) ? body.data : [];
        debugLog(form, "results", items.length);
        render();
      } catch (err) {
        if (err && err.name === "AbortError") {
          return;
        }
        debugLog(form, "fetch failed", err);
        hideList();
      }
    }

    suggestInput.addEventListener("input", function () {
      window.clearTimeout(timer);
      timer = window.setTimeout(fetchSuggestions, DEBOUNCE_MS);
    });

    suggestInput.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") {
        hideList();
      }
      if (ev.key === "Enter" && list.style.display !== "none" && items.length) {
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

  function boot() {
    document.querySelectorAll("form[data-address-autocomplete]").forEach(initForm);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
