// Delegated click handlers so buttons keep working after any re-render.

// Edit buttons in the "Day details" modal
document.addEventListener("click", function (e) {
  const btn = e.target.closest(".edit-event-btn");
  if (!btn) return;
  const id = btn.getAttribute("data-edit-id");
  if (!id) return;
  // priority:'event' => behaves like actionButton; nonce => always triggers
  window.Shiny?.setInputValue?.(
    "edit_event_clicked",
    { id, nonce: Date.now() },
    { priority: "event" }
  );
});

// Timeline tiles — expand/collapse
document.addEventListener("click", function (e) {
  const btn = e.target.closest(".tl-card-btn");
  if (!btn) return;
  const id = btn.getAttribute("data-tl-id");
  if (!id) return;
  window.Shiny?.setInputValue?.("tl_toggle", id, { priority: "event" });
});
