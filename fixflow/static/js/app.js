// 1) Notification badge: ask the API for the unread count every 30 seconds.
// 2) Confirm dialog on forms that have data-confirm.  3) Live search box on the shop list.
(function () {
  const url = document.currentScript.dataset.unreadUrl;
  const badge = document.getElementById("badge");

  async function refreshBadge() {
    if (!badge) return;                       // only logged-in pages have a badge
    try {
      const res = await fetch(url, { credentials: "same-origin" });
      if (!res.ok) return;
      const data = await res.json();
      badge.textContent = data.unread;
      badge.hidden = data.unread === 0;
    } catch (e) { /* offline: ignore */ }
  }
  refreshBadge();
  setInterval(refreshBadge, 30000);

  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (!confirm(form.dataset.confirm)) e.preventDefault();
    });
  });

  const live = document.getElementById("live");
  if (live) {
    live.addEventListener("input", function () {
      const q = live.value.toLowerCase();
      document.querySelectorAll(".shop").forEach(function (card) {
        card.style.display = card.textContent.toLowerCase().includes(q) ? "" : "none";
      });
    });
  }
})();
