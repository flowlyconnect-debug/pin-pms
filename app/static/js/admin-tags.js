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
    const widget = event.target.closest("[data-tag-widget]");
    if (!widget) return;
    const resource = widget.dataset.resource;
    const resourceId = widget.dataset.resourceId;
    try {
      if (event.target.matches("[data-create-tag]")) {
        const name = widget.querySelector("[data-create-tag-name]").value;
        const color = widget.querySelector("[data-create-tag-color]").value;
        await callJson("/admin/api/tags", "POST", { name: name, color: color });
        window.location.reload();
      }
      if (event.target.matches("[data-attach-tag]")) {
        const tagId = widget.querySelector("[data-attach-tag-id]").value;
        await callJson(`/admin/api/${resource}/${resourceId}/tags`, "POST", { tag_id: Number(tagId) });
        window.location.reload();
      }
      if (event.target.matches("[data-detach-tag-id]")) {
        const tagId = event.target.getAttribute("data-detach-tag-id");
        await callJson(`/admin/api/${resource}/${resourceId}/tags/${tagId}`, "DELETE");
        window.location.reload();
      }
    } catch (_err) {
      if (window.toast && typeof window.toast.error === "function") {
        window.toast.error("Tallennus epäonnistui");
      }
    }
  });
})();
