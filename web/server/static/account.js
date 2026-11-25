const activation = document.getElementById("activation-form");
if (activation) {
  const values = new URLSearchParams(window.location.hash.slice(1));
  for (const key of ["uid", "token"]) {
    if (values.has(key)) activation.elements[key].value = values.get(key);
  }
  history.replaceState(history.state, "", window.location.pathname);
  if (!activation.elements.uid.value || !activation.elements.token.value) {
    activation.querySelector("button[type=submit]").disabled = true;
    document.getElementById("activation-error").hidden = false;
  }
}
for (const button of document.querySelectorAll("[data-copy]")) {
  button.addEventListener("click", async () => {
    const field = document.getElementById(button.dataset.copy);
    try { await navigator.clipboard.writeText(field.value); button.textContent = "복사됨"; }
    catch { field.select(); button.textContent = "선택한 링크를 복사하세요"; }
  });
}

for (const input of document.querySelectorAll('input[type="file"][data-max-bytes]')) {
  input.addEventListener("change", () => {
    const oversized = input.files?.[0]?.size > Number(input.dataset.maxBytes);
    input.setCustomValidity(oversized ? "5 MB 이하의 사진을 선택하세요." : "");
    if (oversized) input.reportValidity();
  });
}

// Keep drafts in this tab, scoped to actor and enclosure; never store passwords or CSRF tokens.
const careDraftPrefix = "habitatos:care-draft:";
const careDraftLifetime = 24 * 60 * 60 * 1000;
try {
  for (const key of Object.keys(sessionStorage).filter((key) => key.startsWith(careDraftPrefix))) {
    try {
      const draft = JSON.parse(sessionStorage.getItem(key));
      if (!draft || !Number.isFinite(draft.at) || Date.now() - draft.at > careDraftLifetime) sessionStorage.removeItem(key);
    } catch { sessionStorage.removeItem(key); }
  }
} catch { /* Private browsing can disallow storage. Forms remain usable. */ }
for (const form of document.querySelectorAll('form[action="/logout/"]')) {
  form.addEventListener("submit", () => {
    try { Object.keys(sessionStorage).filter((key) => key.startsWith(careDraftPrefix)).forEach((key) => sessionStorage.removeItem(key)); } catch { /* Continue logout. */ }
  });
}
const careForm = document.getElementById("care-form");
if (careForm) {
  const fields = ["kind", "occurred_at", "weight_g", "note", "submission"];
  const status = document.getElementById("care-draft-status");
  const discard = document.getElementById("care-draft-discard");
  const submit = careForm.querySelector('button[type="submit"]');
  const submitLabel = submit.textContent;
  let dirty = careForm.dataset.bound === "true";
  let submitting = false;
  let storageAvailable = true;
  let draftStartedAt = Date.now();
  try {
    const draft = JSON.parse(sessionStorage.getItem(careForm.dataset.draftKey) || "null");
    if (draft && careForm.dataset.bound !== "true") {
      for (const key of fields) if (typeof draft.values?.[key] === "string") careForm.elements[key].value = draft.values[key];
      draftStartedAt = draft.at;
      dirty = true;
      status.textContent = "이 탭에서 작성하던 내용을 복원했습니다. 확인 후 저장하세요.";
    }
  } catch { storageAvailable = false; }
  function weightVisibility() {
    const weight = careForm.elements.weight_g;
    const visible = careForm.elements.kind.value === "weight";
    weight.closest("p").hidden = !visible;
    weight.disabled = !visible;
    weight.required = visible;
  }
  function saveDraft() {
    dirty = true;
    discard.hidden = false;
    const values = Object.fromEntries(fields.map((key) => [key, careForm.elements[key].value]));
    if (values.kind !== "weight") values.weight_g = "";
    try {
      sessionStorage.setItem(careForm.dataset.draftKey, JSON.stringify({ at: draftStartedAt, values }));
      storageAvailable = true;
    } catch {
      storageAvailable = false;
      status.textContent = "이 브라우저에서는 임시 보관이 불가능합니다. 이동하기 전에 내용을 복사하세요.";
    }
  }
  try {
    const actorPrefix = careForm.dataset.draftKey.split(":").slice(0, 3).join(":") + ":";
    Object.keys(sessionStorage).filter((key) => key.startsWith(careDraftPrefix) && !key.startsWith(actorPrefix)).forEach((key) => sessionStorage.removeItem(key));
  } catch { /* Continue when storage is unavailable. */ }
  weightVisibility();
  discard.hidden = !dirty;
  if (!storageAvailable) status.textContent = "이 브라우저에서는 임시 보관이 불가능합니다. 이동하기 전에 내용을 복사하세요.";
  careForm.addEventListener("input", saveDraft);
  careForm.addEventListener("change", () => { weightVisibility(); saveDraft(); });
  discard.addEventListener("click", () => {
    if (!window.confirm("작성 중인 임시 내용을 지울까요? 저장된 기록은 유지됩니다.")) return;
    try { sessionStorage.removeItem(careForm.dataset.draftKey); } catch { /* Reset still works. */ }
    careForm.reset();
    careForm.elements.note.value = "";
    careForm.elements.weight_g.value = "";
    dirty = false;
    draftStartedAt = Date.now();
    discard.hidden = true;
    weightVisibility();
    status.textContent = "임시 내용을 지웠습니다.";
  });
  window.addEventListener("beforeunload", (event) => {
    if (dirty && !submitting) { event.preventDefault(); event.returnValue = ""; }
  });
  careForm.addEventListener("submit", (event) => {
    if (submitting) { event.preventDefault(); return; }
    saveDraft();
    submitting = true;
    submit.disabled = true;
    submit.textContent = "저장 중…";
    careForm.setAttribute("aria-busy", "true");
  });
  window.addEventListener("pageshow", () => {
    submitting = false;
    submit.disabled = false;
    submit.textContent = submitLabel;
    careForm.removeAttribute("aria-busy");
  });
}
