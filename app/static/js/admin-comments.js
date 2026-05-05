(function () {
  "use strict";

  function csrfToken() {
    const input = document.querySelector('input[name="csrf_token"]');
    return input ? input.value : "";
  }

  async function callJson(url, method, payload) {
    const res = await fetch(url, {
      method: method,
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken(),
      },
      body: payload ? JSON.stringify(payload) : undefined,
      credentials: "same-origin",
    });
    const data = await res.json().catch(function () { return {}; });
    if (!res.ok) throw new Error(data.message || "Request failed");
    return data;
  }

  document.addEventListener("click", async function (event) {
    const widget = event.target.closest("[data-comment-widget]");
    if (!widget) return;
    const resource = widget.dataset.resource;
    const resourceId = widget.dataset.resourceId;
    try {
      if (event.target.matches("[data-comment-create]")) {
        const bodyEl = widget.querySelector("[data-comment-body]");
        const isInternal = widget.querySelector("[data-comment-internal]").checked;
        await callJson(`/admin/api/${resource}/${resourceId}/comments`, "POST", {
          body: bodyEl.value,
          is_internal: isInternal,
        });
        window.location.reload();
      }
      if (event.target.matches("[data-edit-comment-id]")) {
        const id = event.target.getAttribute("data-edit-comment-id");
        const nextBody = window.prompt("Muokkaa kommenttia");
        if (!nextBody) return;
        await callJson(`/admin/api/comments/${id}`, "PATCH", { body: nextBody });
        window.location.reload();
      }
      if (event.target.matches("[data-delete-comment-id]")) {
        const id = event.target.getAttribute("data-delete-comment-id");
        await callJson(`/admin/api/comments/${id}`, "DELETE");
        window.location.reload();
      }
    } catch (_err) {
      window.alert("Kommenttitoiminto epäonnistui");
    }
  });
})();
