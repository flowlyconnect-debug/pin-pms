(function () {
  function initPropertyGallery(root) {
    var main = root.querySelector(".property-gallery__hero");
    var thumbs = Array.from(root.querySelectorAll(".property-gallery__thumb-btn"));
    if (!main || thumbs.length === 0) {
      return;
    }

    var currentIndex = thumbs.findIndex(function (btn) {
      return btn.classList.contains("is-active");
    });
    if (currentIndex < 0) {
      currentIndex = 0;
    }

    function showIndex(index) {
      var count = thumbs.length;
      var next = ((index % count) + count) % count;
      var btn = thumbs[next];
      var url = btn.getAttribute("data-gallery-url");
      if (!url) {
        return;
      }
      main.src = url;
      main.alt = btn.getAttribute("data-gallery-alt") || "";
      thumbs.forEach(function (el, idx) {
        var active = idx === next;
        el.classList.toggle("is-active", active);
        el.setAttribute("aria-pressed", active ? "true" : "false");
      });
      currentIndex = next;
    }

    root.addEventListener("click", function (event) {
      var thumb = event.target.closest(".property-gallery__thumb-btn");
      if (thumb) {
        var thumbIndex = thumbs.indexOf(thumb);
        if (thumbIndex >= 0) {
          showIndex(thumbIndex);
        }
        return;
      }
      if (event.target.closest("[data-gallery-prev]")) {
        showIndex(currentIndex - 1);
      }
      if (event.target.closest("[data-gallery-next]")) {
        showIndex(currentIndex + 1);
      }
    });

    root.addEventListener("keydown", function (event) {
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        showIndex(currentIndex - 1);
      }
      if (event.key === "ArrowRight") {
        event.preventDefault();
        showIndex(currentIndex + 1);
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-property-gallery]").forEach(initPropertyGallery);
  });
})();
