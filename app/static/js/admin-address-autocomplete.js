(function () {
  "use strict";

  var DEBOUNCE_MS = 300;
  var MIN_QUERY_LEN = 3;
  var EMPTY_MESSAGE = "Ei ehdotuksia";

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

    var debugEnabled = form.getAttribute("data-address-debug") === "1";
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
    list.hidden = true;
    wrap.appendChild(list);

    var emptyEl = document.createElement("p");
    emptyEl.className = "address-suggest-empty";
    emptyEl.textContent = EMPTY_MESSAGE;
    emptyEl.hidden = true;
    wrap.appendChild(emptyEl);

    var statusEl = null;
    if (debugEnabled) {
      statusEl = document.createElement("p");
      statusEl.className = "address-suggest-debug";
      statusEl.setAttribute("aria-live", "polite");
      wrap.appendChild(statusEl);
    }

    suggestInput.setAttribute("aria-autocomplete", "list");
    suggestInput.setAttribute("aria-controls", list.id);
    suggestInput.setAttribute("aria-expanded", "false");

    var timer = null;
    var activeController = null;
    var fetchGeneration = 0;
    var items = [];
    var lastQueried = "";

    function setDebugStatus(text) {
      if (!statusEl) {
        return;
      }
      statusEl.textContent = text || "";
      statusEl.hidden = !text;
    }

    function resetSuggestUI() {
      list.classList.remove("is-open");
      list.hidden = true;
      list.innerHTML = "";
      emptyEl.hidden = true;
      items = [];
      lastQueried = "";
      suggestInput.setAttribute("aria-expanded", "false");
      setDebugStatus("");
    }

    function hideList() {
      list.classList.remove("is-open");
      list.hidden = true;
      list.innerHTML = "";
      suggestInput.setAttribute("aria-expanded", "false");
    }

    function showList() {
      list.hidden = false;
      list.removeAttribute("hidden");
      list.classList.add("is-open");
      suggestInput.setAttribute("aria-expanded", "true");
    }

    function showEmptyState() {
      hideList();
      emptyEl.hidden = false;
      setDebugStatus(EMPTY_MESSAGE);
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
      resetSuggestUI();
    }

    function renderResults() {
      emptyEl.hidden = true;
      list.innerHTML = "";
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
      showList();
      if (debugEnabled) {
        setDebugStatus(items.length + " ehdotusta");
      }
    }

    function renderForQuery(query) {
      if (query !== lastQueried) {
        return;
      }
      if (!items.length) {
        showEmptyState();
        return;
      }
      renderResults();
    }

    async function fetchSuggestions() {
      var q = (suggestInput.value || "").trim();
      if (q.length < MIN_QUERY_LEN) {
        resetSuggestUI();
        return;
      }

      if (activeController) {
        activeController.abort();
      }
      activeController = new AbortController();
      var generation = ++fetchGeneration;
      lastQueried = q;
      emptyEl.hidden = true;
      hideList();
      if (debugEnabled) {
        setDebugStatus("Haetaan...");
      }

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
        if (generation !== fetchGeneration) {
          return;
        }
        if (!res.ok) {
          debugLog(form, "http error", res.status);
          items = [];
          renderForQuery(q);
          return;
        }
        var body = await res.json();
        if (generation !== fetchGeneration) {
          return;
        }
        items =
          body && body.success && Array.isArray(body.data) ? body.data : [];
        debugLog(form, "results", items.length);
        renderForQuery(q);
      } catch (err) {
        if (err && err.name === "AbortError") {
          return;
        }
        if (generation !== fetchGeneration) {
          return;
        }
        debugLog(form, "fetch failed", err);
        items = [];
        renderForQuery(q);
      }
    }

    suggestInput.addEventListener("input", function () {
      var q = (suggestInput.value || "").trim();
      if (q.length < MIN_QUERY_LEN) {
        resetSuggestUI();
        return;
      }
      window.clearTimeout(timer);
      timer = window.setTimeout(fetchSuggestions, DEBOUNCE_MS);
    });

    suggestInput.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") {
        resetSuggestUI();
      }
      if (ev.key === "Enter" && list.classList.contains("is-open") && items.length) {
        ev.preventDefault();
        applySelection(items[0]);
      }
    });

    document.addEventListener("mousedown", function (ev) {
      if (!wrap.contains(ev.target)) {
        resetSuggestUI();
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
