(function () {
  "use strict";

  var widgets = document.querySelectorAll("[data-quick-availability]");
  if (!widgets.length) return;

  function formatRange(data) {
    if (!data || !data.start_date || !data.end_date) return "";
    if (data.start_date === data.end_date) return data.start_date;
    return data.start_date + " - " + data.end_date;
  }

  function addDays(dateText, days) {
    var parts = String(dateText || "").split("-");
    if (parts.length !== 3) return dateText || "";
    var date = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
    date.setDate(date.getDate() + days);
    var year = date.getFullYear();
    var month = String(date.getMonth() + 1).padStart(2, "0");
    var day = String(date.getDate()).padStart(2, "0");
    return year + "-" + month + "-" + day;
  }

  function formatNextReservation(days) {
    if (days === null || days === undefined) return "Ei seuraavaa varausta";
    if (Number(days) === 0) return "Seuraava varaus tänään";
    return "Seuraava varaus " + days + " pv päästä";
  }

  function buildReservationUrl(unitId, startDate, endDate) {
    var params = new URLSearchParams({
      unit_id: String(unitId),
      start_date: startDate,
      end_date: addDays(endDate, 1),
    });
    return "/admin/reservations/new?" + params.toString();
  }

  function renderRooms(container, rooms, data) {
    container.innerHTML = "";
    if (!rooms.length) return;
    var list = document.createElement("ul");
    list.className = "admin-quick-availability-list";
    rooms.forEach(function (room) {
      var item = document.createElement("li");
      var title = document.createElement("span");
      var meta = document.createElement("span");
      var details = document.createElement("span");
      var link = document.createElement("a");
      title.textContent = (room.property || "Kohde") + " / " + (room.unit || "Huone");
      meta.textContent = "Vapaita päiviä: " + room.free_days;
      details.textContent = formatNextReservation(room.next_reservation_in_days);
      link.href = buildReservationUrl(room.unit_id, data.start_date, data.end_date);
      link.textContent = "Uusi varaus";
      item.appendChild(title);
      item.appendChild(meta);
      item.appendChild(details);
      item.appendChild(link);
      list.appendChild(item);
    });
    container.appendChild(list);
  }

  function initWidget(widget) {
    var endpoint = widget.getAttribute("data-endpoint") || "/admin/availability/quick";
    var buttons = widget.querySelectorAll("[data-quick-range]");
    var status = widget.querySelector("[data-quick-status]");
    var results = widget.querySelector("[data-quick-results]");
    if (!buttons.length || !status || !results) return;

    buttons.forEach(function (button) {
      button.addEventListener("click", async function () {
        var range = button.getAttribute("data-quick-range") || "today";
        buttons.forEach(function (item) {
          item.classList.toggle("is-active", item === button);
        });
        status.textContent = "Haetaan vapaita huoneita...";
        results.innerHTML = "";

        try {
          var response = await fetch(endpoint + "?range=" + encodeURIComponent(range), {
            credentials: "same-origin",
          });
          var body = await response.json();
          if (!response.ok || !body || body.success !== true) {
            throw new Error("quick availability failed");
          }
          var data = body.data || {};
          var rooms = data.free_units || [];
          if (!rooms.length) {
            status.textContent = "Ei vapaita huoneita valitulla aikavälillä.";
            return;
          }
          status.textContent = rooms.length + " vapaata huonetta · " + formatRange(data);
          renderRooms(results, rooms, data);
        } catch (err) {
          status.textContent = "Saatavuuden haku epäonnistui.";
        }
      });
    });
  }

  widgets.forEach(initWidget);
})();
