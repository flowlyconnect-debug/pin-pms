(function () {
  "use strict";

  var widgets = document.querySelectorAll("[data-quick-availability]");
  if (!widgets.length) return;

  function formatRange(data) {
    if (!data || !data.start_date || !data.end_date) return "";
    if (data.start_date === data.end_date) return data.start_date;
    return data.start_date + " - " + data.end_date;
  }

  function renderRooms(container, rooms) {
    container.innerHTML = "";
    if (!rooms.length) return;
    var list = document.createElement("ul");
    list.className = "admin-quick-availability-list";
    rooms.forEach(function (room) {
      var item = document.createElement("li");
      var title = document.createElement("span");
      var meta = document.createElement("span");
      title.textContent = room.name || "Huone";
      meta.textContent = room.property_name || "";
      item.appendChild(title);
      if (meta.textContent) item.appendChild(meta);
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
          var rooms = data.available_rooms || [];
          if (!rooms.length) {
            status.textContent = "Ei vapaita huoneita valitulla aikavälillä.";
            return;
          }
          status.textContent = rooms.length + " vapaata huonetta · " + formatRange(data);
          renderRooms(results, rooms);
        } catch (err) {
          status.textContent = "Saatavuuden haku epäonnistui.";
        }
      });
    });
  }

  widgets.forEach(initWidget);
})();
