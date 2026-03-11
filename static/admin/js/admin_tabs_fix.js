(function () {
  function activateTab(link) {
    const target = link.getAttribute("href");
    if (!target || !target.startsWith("#")) return;

    const pane = document.querySelector(target);
    if (!pane) return;

    // deactivate links
    document.querySelectorAll(".nav-tabs .nav-link").forEach(a => {
      a.classList.remove("active");
      a.setAttribute("aria-selected", "false");
    });

    // deactivate panes
    document.querySelectorAll(".tab-content .tab-pane").forEach(p => {
      p.classList.remove("active", "show");
    });

    // activate selected
    link.classList.add("active");
    link.setAttribute("aria-selected", "true");
    pane.classList.add("active", "show");
  }

  document.addEventListener("click", function (e) {
    const link = e.target.closest(".nav-tabs .nav-link");
    if (!link) return;

    const href = link.getAttribute("href") || "";
    if (!href.startsWith("#")) return;

    e.preventDefault();
    // keep URL updated (optional)
    history.replaceState(null, "", href);
    activateTab(link);
  });

  document.addEventListener("DOMContentLoaded", function () {
    // activate by hash, else first tab
    const hash = window.location.hash;
    if (hash) {
      const link = document.querySelector(`.nav-tabs .nav-link[href="${hash}"]`);
      if (link) {
        activateTab(link);
        return;
      }
    }
    const first = document.querySelector(".nav-tabs .nav-link");
    if (first) activateTab(first);
  });
})();