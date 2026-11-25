"use strict";
const $ = id => document.getElementById(id);
const labels = {usual:"평소와 비슷해 보임", paler:"평소보다 옅어 보임", started:"탈피 시작·진행 확인", completed:"탈피 완료 확인", uncertain:"판단하기 어려움"};
let state = null;
let pending = null;
let exportUrl = null;
function localNow() {
  const date = new Date();
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 19);
}
function status(message, error = false) {
  $("saveStatus").textContent = message;
  $("saveStatus").dataset.error = String(error);
}
async function request(path, options = {}) {
  const response = await fetch(path, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || "저장 요청을 완료하지 못했습니다.");
  return body;
}
async function refresh() {
  state = await request("/api/appearance");
  $("storageMode").textContent = state.dataset_kind === "test" ? "합성 검사 전용 저장소" : "이 컴퓨터에 저장";
  $("recordCount").textContent = `${state.records.length}개 관찰 · 예측 모델 미학습`;
  $("emptyState").hidden = state.records.length > 0;
  $("entries").replaceChildren();
  for (const record of state.records.slice(-30).reverse()) {
    const row = record.input;
    const item = document.createElement("li");
    const title = document.createElement("strong");
    title.textContent = `${row.animal_id} · ${labels[row.assessment]}`;
    const time = document.createElement("p"); time.className = "small";
    time.textContent = `${new Date(row.earliest_at).toLocaleString()}${row.earliest_at !== row.latest_at ? " ~ " + new Date(row.latest_at).toLocaleString() : ""} · ${row.observer}`;
    const note = document.createElement("p"); note.textContent = row.note;
    item.append(title, time, note);
    if (record.photo) {
      const attachment = document.createElement("p"); attachment.className = "small";
      attachment.textContent = `첨부: ${record.photo.original_name} · 색상 검수 전`;
      item.append(attachment);
    }
    $("entries").append(item);
  }
  $("entryFields").disabled = false;
  $("exportEntries").disabled = false;
}
$("earliestAt").value = localNow();
$("diaryForm").addEventListener("submit", async event => {
  event.preventDefault();
  $("entryFields").disabled = true;
  let saved = false;
  try {
    const file = $("photo").files[0];
    if (file && file.size > 8 * 1024 ** 2) throw new Error("사진은 8MiB 이하로 선택해 주세요.");
    const first = new Date($("earliestAt").value).toISOString();
    const last = $("latestAt").value ? new Date($("latestAt").value).toISOString() : first;
    if (last < first || new Date(last) > new Date()) throw new Error("관찰 구간의 순서와 미래 시각 여부를 확인해 주세요.");
    status("관찰을 저장하고 있습니다.");
    let photoId = null;
    if (file) {
      const photo = await request("/api/appearance/photo", {method:"POST", headers:{"X-Lab-Token":state.token, "X-Filename":encodeURIComponent(file.name)}, body:file});
      photoId = photo.id;
    }
    const row = {animal_id:$("animalId").value.trim(), enclosure_id:$("enclosureId").value.trim() || null,
      observer:$("observer").value.trim(), earliest_at:first, latest_at:last, assessment:$("assessment").value,
      note:$("note").value.trim(), identity_confirmed:$("identityConfirmed").checked, photo_id:photoId};
    const content = JSON.stringify(row);
    // Preserve the request ID after an ambiguous network failure; edits create a new record.
    if (!pending || pending.content !== content) pending = {content, id:crypto.randomUUID().replaceAll("-", "")};
    await request("/api/appearance/records", {method:"POST", headers:{"Content-Type":"application/json", "X-Lab-Token":state.token}, body:JSON.stringify({...row, record_id:pending.id})});
    saved = true; pending = null;
    $("note").value = ""; $("photo").value = ""; $("identityConfirmed").checked = false;
    $("latestAt").value = ""; $("earliestAt").value = localNow(); $("assessment").value = "uncertain";
    await refresh();
    status("관찰을 저장했습니다.");
  } catch (error) {
    status(saved ? `저장은 완료됐지만 목록을 새로 불러오지 못했습니다: ${error.message}` : `저장 확인 실패: ${error.message} 입력 내용은 유지했습니다.`, true);
  } finally { $("entryFields").disabled = false; }
});
$("exportEntries").addEventListener("click", () => {
  if (exportUrl) URL.revokeObjectURL(exportUrl);
  const {token, ...data} = state;
  exportUrl = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2) + "\n"], {type:"application/json"}));
  const link = document.createElement("a"); link.href = exportUrl; link.download = "crested-observations.json";
  document.body.append(link); link.click(); link.remove();
});
refresh().catch(error => status(`기록 화면을 열 수 없습니다: ${error.message} 새로고침해 주세요.`, true));
