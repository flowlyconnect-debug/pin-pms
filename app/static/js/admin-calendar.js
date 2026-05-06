(function () {
  "use strict";
  function showError(message) {
    if (window.toast && typeof window.toast.error === "function") {
      window.toast.error(message);
      return;
    }
    console.error(message);
  }

  function init() {
    var el = document.getElementById("calendar");
    if (!el || typeof FullCalendar === "undefined") {
      return;
    }
    var propEl = document.getElementById("filter-property");
    var unitEl = document.getElementById("filter-unit");
    var typeEl = document.getElementById("filter-event-types");
    var eventsUrl = el.dataset.eventsUrl || "";
    var reservationsBaseUrl = el.dataset.reservationsBaseUrl || "/admin/reservations";
    var csrfMeta = document.querySelector('meta[name="csrf-token"]');
    var csrfToken = csrfMeta ? csrfMeta.getAttribute("content") : "";
    var fiDateFormat = new Intl.DateTimeFormat("fi-FI");

    function syncUnitOptionsForProperty() {
      if (!unitEl || !propEl) {
        return;
      }
      var pid = propEl.value;
      var current = unitEl.value;
      for (var i = 0; i < unitEl.options.length; i++) {
        var opt = unitEl.options[i];
        if (!opt.value) {
          opt.hidden = false;
          continue;
        }
        var opid = opt.getAttribute("data-property-id");
        opt.hidden = Boolean(pid) && String(opid) !== String(pid);
      }
      if (current) {
        for (var j = 0; j < unitEl.options.length; j++) {
          if (unitEl.options[j].value === current && unitEl.options[j].hidden) {
            unitEl.value = "";
            break;
          }
        }
      }
    }

    function calendarFilterParams() {
      var params = {};
      if (propEl && propEl.value) {
        params.property_id = propEl.value;
      }
      if (unitEl && unitEl.value) {
        params.unit_id = unitEl.value;
      }
      if (typeEl && typeEl.value) {
        params.event_types = typeEl.value;
      }
      return params;
    }

    function buildEventTooltip(event) {
      var props = event.extendedProps || {};
      var startLabel = event.start ? fiDateFormat.format(event.start) : "";
      var endLabel = event.end ? fiDateFormat.format(event.end) : "";
      var reservationId = "";
      if (event.id !== undefined && event.id !== null && event.id !== "") {
        reservationId = String(event.id);
      } else if (props.reservation_id !== undefined && props.reservation_id !== null) {
        reservationId = String(props.reservation_id);
      }
      return [
        "Vieras: " + (props.guest_name || "Tuntematon"),
        "Varaus-ID: " + (reservationId || "-"),
        "Paivat: " + (startLabel && endLabel ? startLabel + " - " + endLabel : startLabel || endLabel || "-"),
      ].join("\n");
    }

    function navigateToEvent(info) {
      var rid = info.event.id;
      if (rid !== undefined && rid !== null && rid !== "" && /^\d+$/.test(String(rid))) {
        window.location.href = reservationsBaseUrl + "/" + String(rid);
        return true;
      }
      if (info.event.url) {
        window.location.href = info.event.url;
        return true;
      }
      return false;
    }

    var calendar = new FullCalendar.Calendar(el, {
      initialView: "dayGridMonth",
      headerToolbar: {
        left: "prev,next today",
        center: "title",
        right: "dayGridMonth,timeGridWeek,listMonth",
      },
      dayMaxEvents: true,
      editable: true,
      eventDurationEditable: true,
      eventResizableFromStart: false,
      selectable: false,
      eventSources: [{ url: eventsUrl, method: "GET", extraParams: calendarFilterParams }],
      eventDidMount: function (info) {
        var props = info.event.extendedProps || {};
        if (props.status === "cancelled") {
          info.el.classList.add("fc-event-peruttu");
        }
        var tooltip = buildEventTooltip(info.event);
        info.el.title = tooltip;
        info.el.setAttribute("aria-label", tooltip);
        info.el.setAttribute("tabindex", "0");
        info.el.setAttribute("role", "link");
        if (info.event.id !== undefined && info.event.id !== null && info.event.id !== "") {
          info.el.setAttribute("data-reservation-id", String(info.event.id));
        }
        if (/^\d+$/.test(String(info.event.id || ""))) {
          info.el.setAttribute("data-href", reservationsBaseUrl + "/" + String(info.event.id));
        } else if (info.event.url) {
          info.el.setAttribute("data-href", info.event.url);
        }
        info.el.addEventListener("keydown", function (event) {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            navigateToEvent(info);
          }
        });
      },
      eventClick: function (info) {
        info.jsEvent.preventDefault();
        navigateToEvent(info);
      },
      eventDrop: function (info) {
        var ev = info.event;
        if ((ev.extendedProps && ev.extendedProps.status && !ev.extendedProps.unit_id) || ev.editable === false) {
          info.revert();
          return;
        }
        var start = ev.startStr ? ev.startStr.slice(0, 10) : null;
        var end = ev.endStr ? ev.endStr.slice(0, 10) : null;
        if (!start) {
          info.revert();
          return;
        }
        if (!end) {
          end = start;
        }
        var props = ev.extendedProps || {};
        if (props.unit_id === undefined || props.unit_id === null) {
          info.revert();
          showError("Huone puuttuu tältä varaukselta.");
          return;
        }
        fetch(reservationsBaseUrl + "/" + String(ev.id) + "/move", {
          method: "PATCH",
          headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
          body: JSON.stringify({ start_date: start, end_date: end, unit_id: props.unit_id }),
        })
          .then(function (res) {
            return res.json().then(function (body) {
              if (!res.ok || !body.success) {
                info.revert();
                showError((body && body.error && body.error.message) || "Siirto epäonnistui.");
                return;
              }
              info.view.calendar.refetchEvents();
            });
          })
          .catch(function () {
            info.revert();
            showError("Siirto epäonnistui.");
          });
      },
      eventResize: function (info) {
        var ev = info.event;
        if (ev.editable === false) {
          info.revert();
          return;
        }
        var start = ev.startStr ? ev.startStr.slice(0, 10) : null;
        var end = ev.endStr ? ev.endStr.slice(0, 10) : null;
        if (!start || !end) {
          info.revert();
          return;
        }
        fetch(reservationsBaseUrl + "/" + String(ev.id) + "/resize", {
          method: "PATCH",
          headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
          body: JSON.stringify({ start_date: start, end_date: end }),
        })
          .then(function (res) {
            return res.json().then(function (body) {
              if (!res.ok || !body.success) {
                info.revert();
                showError(
                  (body && body.error && body.error.message) || "Muutoksen tallennus epäonnistui."
                );
                return;
              }
              info.view.calendar.refetchEvents();
            });
          })
          .catch(function () {
            info.revert();
            showError("Muutoksen tallennus epäonnistui.");
          });
      },
    });

    calendar.render();
    syncUnitOptionsForProperty();
    if (propEl) {
      propEl.addEventListener("change", function () {
        syncUnitOptionsForProperty();
        calendar.refetchEvents();
      });
    }
    if (unitEl) {
      unitEl.addEventListener("change", function () {
        calendar.refetchEvents();
      });
    }
    if (typeEl) {
      typeEl.addEventListener("change", function () {
        calendar.refetchEvents();
      });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
