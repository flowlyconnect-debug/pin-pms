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
        info.el.title =
          "Asiakas: " +
          (props.guest_name || "") +
          "\n" +
          "Kohde: " +
          (props.property_name || "") +
          "\n" +
          "Huone: " +
          (props.unit_name || "") +
          "\n" +
          "Tila: " +
          (props.status || "") +
          "\n" +
          "Alku: " +
          (info.event.start ? fiDateFormat.format(info.event.start) : "") +
          "\n" +
          "Loppu: " +
          (info.event.end ? fiDateFormat.format(info.event.end) : "");
      },
      eventClick: function (info) {
        info.jsEvent.preventDefault();
        var rid = info.event.id;
        if (rid !== undefined && rid !== null && rid !== "" && /^\d+$/.test(String(rid))) {
          window.location.href = reservationsBaseUrl + "/" + String(rid);
          return;
        }
        if (info.event.url) {
          window.location.href = info.event.url;
        }
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
