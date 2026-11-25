'use strict';

const $ = id => document.getElementById(id);
let state, currentImage, currentJob, currentWindow, imageVersion = 0, caseVersion = 0;
const splitNames = {train: '추가 학습', val: '개발 검증', test: '시험'};
const jobNames = {queued: '대기 중', running: '분석 중', complete: '완료', failed: '실패', interrupted: '중단됨'};
const reasonNames = {
  insufficient_observation: '관측 부족: 가림·검출 누락·추적 끊김을 정상이나 활동량 0으로 처리하지 않았습니다.',
  no_reviewed_reference: '검토한 정상 기준이 없어 이상 여부를 판단하지 않았습니다.',
  context_mismatch: '개체·설치·시간대·촬영 조건 또는 모델이 기준과 다릅니다.',
  reference_data_reuse: '기준을 만들 때 사용한 자료입니다. 독립 평가로 계산하지 않습니다.',
  not_after_calibration: '기준 보정보다 나중에 촬영한 새 날짜 자료가 필요합니다.'
};

function error(message) {
  $('error').textContent = message;
  $('error').hidden = !message;
}

async function api(path, body) {
  const options = body === undefined ? {} : {
    method: 'POST',
    headers: {'Content-Type': 'application/json', 'X-Lab-Token': state.token},
    body: JSON.stringify(body)
  };
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '요청 실패');
  return data;
}

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}

function describeModel() {
  const model = state.models.find(item => item.key === $('model').value);
  $('modelNote').textContent = model?.backend === 'sam2-hybrid'
    ? '최근 프레임의 동물 영역을 이어서 추적하는 실험 모델입니다. 초당 2장 분석하며 실시간 처리는 보장하지 않습니다. 초기 누락·가림 뒤 번호 변경이 생길 수 있습니다. 활동량과 이상 여부는 계산하지 않습니다.'
    : '각 표본의 위치 검출과 추적을 수행합니다. 추적 번호는 실제 개체 신원이 아니며, 직접 촬영한 검토 자료가 없으면 이상 여부를 판단하지 않습니다.';
}
$('model').onchange = describeModel;

function sourceLink(text, url) {
  const link = node('a', text);
  try {
    const parsed = new URL(url);
    if (['https:', 'http:'].includes(parsed.protocol)) {
      link.href = parsed.href;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
    }
  } catch { /* Leave an invalid source address as plain text. */ }
  return link;
}

function panel(name) {
  for (const element of document.querySelectorAll('.panel')) element.hidden = element.id !== name;
  for (const tab of document.querySelectorAll('.tab')) {
    const active = tab.dataset.panel === name;
    tab.classList.toggle('active', active);
    tab.setAttribute('aria-pressed', String(active));
  }
  if (name !== 'videos') {
    $('reviewVideo').pause();
    $('referenceVideo').pause();
    $('visualMemoryVideo').pause();
  }
}
for (const tab of document.querySelectorAll('.tab')) tab.onclick = () => {
  panel(tab.dataset.panel);
  if (tab.dataset.panel === 'reference') renderEvaluation().catch(e => error(e.message));
};

function gallery() {
  const collection = $('collection').value;
  const inventory = state.images.filter(row => (row.collection || 'crested') === collection);
  $('photoCount').textContent = inventory.length;
  $('splitCounts').textContent = ['train', 'val', 'test'].map(split => inventory.filter(row => row.split === split).length).join(' / ');
  $('humanCount').textContent = `${inventory.filter(row => row.review_method === 'human').length}장`;
  const positiveCount = inventory.filter(row => row.references.length).length;
  $('datasetNote').textContent = ['public', 'expanded', 'camera', 'captive'].includes(collection)
    ? `이전 학습 자료의 기록입니다. 도마뱀 표시가 없다는 이유로 배경 처리했던 공개 사진에서 라벨 누락을 발견해, 확인 전 사진은 정답 비교에서 제외했습니다. 현재 표시: 도마뱀 라벨 ${positiveCount}장 · 별도 검토한 배경 ${inventory.length - positiveCount}장. 원본과 출처는 보존했으며, 이전 점수를 실사용 성능으로 판단할 수 없습니다.`
    : '기존 크레스티드 전용 자료입니다. 다른 종을 포함한 음성 사진은 도마뱀 공통 탐지의 배경 정답으로 재사용하지 않았습니다.';
  for (const option of $('split').options) {
    if (option.value !== 'all') option.textContent = `${splitNames[option.value]} ${inventory.filter(row => row.split === option.value).length}장`;
  }
  if (collection === 'captive') {
    $('trainingOutcome').textContent = state.captive_experiment?.summary || '사육 환경 보강 실험의 검증 결과를 준비 중입니다.';
  } else if (collection === 'camera') {
    $('trainingOutcome').textContent = state.camera_experiment?.summary || '카메라 조건 보강 실험의 학습·검증 결과를 준비 중입니다. 아직 완료된 모델로 판단하지 않습니다.';
  } else if (collection === 'expanded') {
    $('trainingOutcome').textContent = state.diversity_experiment?.summary || '자료 다양화 후보를 검증 중입니다. 사진의 예측 박스와 별도 영상의 탐지·추적 결과를 함께 확인해야 합니다.';
  } else if (collection === 'public') {
    $('trainingOutcome').textContent = state.public_research?.summary || '공개 자료 확장 실험의 결과를 확인 중입니다. 사진 수는 정확도나 이상 탐지 성능을 뜻하지 않습니다.';
  } else if (state.training_experiment) {
    $('trainingOutcome').textContent = state.training_experiment.decision;
  }
  const rows = inventory.filter(row => {
    const kind = $('kind').value;
    const prediction = row.predictions.captive_lizard || row.predictions.camera_lizard || row.predictions.diverse_lizard || row.predictions.public_lizard || row.predictions.candidate;
    return ($('split').value === 'all' || row.split === $('split').value) &&
      (kind === 'all' || (kind === 'positive' && row.references.length) ||
       (kind === 'negative' && !row.references.length) ||
       (kind === 'error' && prediction && (prediction.false_positive || prediction.false_negative)));
  });
  if (!rows.some(row => row.id === currentImage?.id)) {
    currentImage = rows[0];
    drawImage().catch(e => error(e.message));
  }
  $('gallery').replaceChildren();
  $('galleryCount').textContent = `${rows.length}장 · 선택하면 크게 볼 수 있습니다`;
  for (const row of rows) {
    const button = node('button', undefined, 'thumb');
    button.type = 'button';
    button.setAttribute('aria-label', `${row.id}, ${splitNames[row.split]}, ${row.references.length ? '대상 있음' : '대상 없음'}`);
    const img = node('img');
    img.src = row.image;
    img.alt = '';
    img.loading = 'lazy';
    button.append(img, node('span', row.display_name || row.id.replace('commons-', '')));
    button.classList.toggle('selected', currentImage?.id === row.id);
    const prediction = row.predictions.captive_lizard || row.predictions.camera_lizard || row.predictions.diverse_lizard || row.predictions.public_lizard || row.predictions.candidate;
    button.classList.toggle('error', !!(prediction && (prediction.false_positive || prediction.false_negative)));
    button.onclick = () => {
      currentImage = row;
      gallery();
      drawImage().catch(e => error(e.message));
    };
    $('gallery').append(button);
  }
}

async function drawImage() {
  const row = currentImage;
  const version = ++imageVersion;
  const canvas = $('photoCanvas');
  if (!row) {
    $('imageTitle').textContent = '해당 사진이 없습니다.';
    for (const id of ['imageSplit', 'imageResults', 'imageCredit', 'imageMeaning']) $(id).replaceChildren();
    canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height);
    return;
  }
  $('imageTitle').textContent = row.display_name || row.id;
  $('imageSplit').textContent = splitNames[row.split];
  const img = new Image();
  img.src = row.image;
  await img.decode();
  if (version !== imageVersion) return;
  canvas.width = row.width;
  canvas.height = row.height;
  const context = canvas.getContext('2d');
  context.drawImage(img, 0, 0);
  function box(rect, color, dash, label) {
    context.strokeStyle = color;
    context.lineWidth = Math.max(3, row.width / 220);
    context.setLineDash(dash);
    context.strokeRect(rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1]);
    context.setLineDash([]);
    const fontSize = Math.max(14, row.width / 45);
    context.font = `${fontSize}px sans-serif`;
    const top = Math.max(fontSize + 6, rect[1] - 6);
    context.fillStyle = color;
    context.fillRect(rect[0], top - fontSize, context.measureText(label).width + 8, fontSize + 6);
    context.fillStyle = 'white';
    context.fillText(label, rect[0] + 4, top);
  }
  if ($('showReference').checked) for (const rect of row.references) box(rect, '#167549', [], row.review_method === 'publisher_annotations' ? '연구자 라벨' : 'AI 기준');
  for (const [key, toggle, color, label] of [
    ['baseline', 'showBaseline', '#2462bf', '기존'], ['candidate', 'showCandidate', '#bf640c', '후보'], ['public_lizard', 'showPublic', '#bf640c', '공개 확장'], ['diverse_lizard', 'showPublic', '#bf640c', '자료 다양화 후보'], ['camera_lizard', 'showPublic', '#bf640c', '카메라 조건 보강'], ['captive_lizard', 'showPublic', '#bf640c', '사육 환경 보강']
  ]) {
    if ($(toggle).checked && row.predictions[key]) {
      for (const prediction of row.predictions[key].predictions) {
        box(prediction.xyxy, color, key === 'baseline' ? [9, 6] : [], `${label} ${prediction.confidence.toFixed(2)}`);
      }
    }
  }
  $('imageResults').replaceChildren();
  for (const [key, label] of (row.collection === 'captive' ? [['baseline', '이전 1,674장 모델'], ['captive_lizard', '사육 환경 보강 · 1,693장 후보']] : row.collection === 'camera' ? [['baseline', '이전 1,613장 모델'], ['camera_lizard', '카메라 조건 보강 · 1,674장 모델']] : row.collection === 'expanded' ? [['baseline', '이전 624장 모델'], ['diverse_lizard', '자료 다양화 · 1,613장 모델']] : row.collection === 'public' ? [['public_lizard', '공개 자료 확장 모델']] : [['baseline', '기존 모델'], ['candidate', '후보 모델']])) {
    const card = node('div');
    const prediction = row.predictions[key];
    card.append(node('strong', label), node('p', prediction ?
      `정탐 ${prediction.true_positive} · 누락 ${prediction.false_negative} · 잘못 찾은 박스 ${prediction.false_positive}` :
      '이 사진의 저장된 비교 예측은 없습니다.'));
    $('imageResults').append(card);
  }
  $('imageCredit').replaceChildren(node('span', `${row.source.attribution} · ${row.source.license} · `),
    sourceLink('원본·사용 조건', row.source.url));
  $('imageMeaning').textContent = row.references.length ?
    `기준은 ${row.review_method === 'publisher_annotations' ? '데이터 공개 연구자가 제공한 라벨' : 'AI가 검토한 라벨'}입니다. 표시된 신뢰도는 정확도나 건강 확률이 아닙니다.` :
    `${row.target === 'lizard' ? '도마뱀이' : '크레스티드 게코가'} 없는 것으로 표시된 사진입니다. 모델 박스가 나오면 오검출로 집계합니다. 원본 라벨의 누락 여부도 검토해야 합니다.`;
}
for (const id of ['collection', 'split', 'kind']) $(id).onchange = gallery;
for (const id of ['showReference', 'showBaseline', 'showCandidate', 'showPublic']) {
  $(id).onchange = () => drawImage().catch(e => error(e.message));
}

function renderVerification() {
  const evidence = state.verification;
  $('verificationCase').hidden = !evidence;
  if (!evidence) return;
  $('verificationMeaning').textContent = evidence.meaning;
  $('verificationResults').replaceChildren();
  for (const result of evidence.results) {
    const card = node('div');
    card.append(node('strong', result.label), node('p',
      `${result.samples}개 표본 중 ${result.false_positive_samples}개 순간에서 다른 종을 크레로 표시 · 해당 박스 ${result.false_positive_boxes}개`));
    const button = node('button', '박스가 표시된 영상 확인');
    button.type = 'button';
    button.onclick = () => showJob(result.job_id).catch(e => error(e.message));
    card.append(button);
    $('verificationResults').append(card);
  }
  $('verificationCredit').replaceChildren(node('span', `${evidence.author} · ${evidence.license} · `),
    sourceLink('원본 영상', evidence.url), node('p',
      '다른 종 1개 영상을 81번 살펴본 결과입니다. 81개 독립 영상의 시험이나 정확도 수치가 아닙니다. 크레스티드를 잘 찾는지와 이상 행동을 잡는지는 이 영상으로 알 수 없습니다. 종 판별 검사와 동물 위치·행동 검증을 구분해야 합니다.'));
  const misses = {};
  for (const key of ['baseline', 'candidate']) {
    const rows = state.images.filter(row => row.split === 'val' && row.predictions[key]);
    misses[key] = rows.reduce((sum, row) => ({missed: sum.missed + row.predictions[key].false_negative, total: sum.total + row.predictions[key].false_negative + row.predictions[key].true_positive}), {missed: 0, total: 0});
  }
  $('detectorTradeoff').textContent = `후보가 더 잘 작동한다고 확정할 수 없습니다. 별도 개발용 사진에서는 AI 기준 박스 ${misses.baseline.total}개 중 기존 모델이 ${misses.baseline.missed}개, 후보가 ${misses.candidate.missed}개를 놓쳤습니다. 실제 사육장 영상의 누락률·오경보율은 아직 미측정입니다.`;
  $('caseInspection').hidden = !evidence.frames?.length;
  if (evidence.frames?.length) {
    const selected = $('caseFrame').value;
    $('caseFrame').replaceChildren();
    for (const frame of evidence.frames) {
      const option = node('option', `${frame.offset_seconds.toFixed(3)}초 · 원본 프레임 ${frame.frame_index}`);
      option.value = String(frame.frame_index);
      $('caseFrame').append(option);
    }
    if (evidence.frames.some(frame => String(frame.frame_index) === selected)) $('caseFrame').value = selected;
    renderCaseFrame().catch(e => error(e.message));
  }
}

async function renderCaseFrame() {
  const frame = state.verification.frames.find(row => String(row.frame_index) === $('caseFrame').value);
  if (!frame) return;
  const version = ++caseVersion;
  const img = new Image();
  img.src = frame.image;
  await img.decode();
  if (version !== caseVersion) return;
  $('casePanels').replaceChildren();
  for (const [key, title] of [[null, '원본 · 기대 박스 0개'], ['baseline', '기존 모델'], ['candidate', '후보 모델']]) {
    const card = node('article');
    const boxes = key ? frame.predictions[key] : [];
    card.append(node('h3', title));
    const canvas = node('canvas');
    canvas.width = frame.width;
    canvas.height = frame.height;
    canvas.setAttribute('aria-label', `${title}, 원본 ${frame.offset_seconds.toFixed(3)}초, 표시 박스 ${boxes.length}개`);
    const context = canvas.getContext('2d');
    context.drawImage(img, 0, 0, frame.width, frame.height);
    for (const [index, box] of boxes.entries()) {
      const [x1, y1, x2, y2] = box.xyxy;
      context.strokeStyle = '#ffb226';
      context.lineWidth = Math.max(4, frame.width / 240);
      context.strokeRect(x1, y1, x2 - x1, y2 - y1);
      const fontSize = frame.width / 32;
      context.font = `${fontSize}px sans-serif`;
      const text = `#${index + 1}`;
      const labelWidth = context.measureText(text).width + 12;
      const x = Math.max(0, Math.min(x1, frame.width - labelWidth));
      const y = Math.max(fontSize + 12, y1);
      context.fillStyle = '#18231e';
      context.fillRect(x, y - fontSize - 8, labelWidth, fontSize + 14);
      context.fillStyle = '#ffb226';
      context.fillText(text, x + 6, y);
    }
    card.append(canvas, node('p', key ? (boxes.length ? `추측 박스 ${boxes.length}개 · 모두 오검출` : '이 장면에서는 기대와 일치: 박스 없음') : '다른 종인 집도마뱀붙이 영상'));
    if (boxes.length) card.append(node('p', '박스별 점수: ' + boxes.map((box, index) => `#${index + 1} ${box.confidence.toFixed(2)}`).join(' · '), 'small'));
    $('casePanels').append(card);
  }
}
$('caseFrame').onchange = () => renderCaseFrame().catch(e => error(e.message));

function renderJobs() {
  const container = $('jobs');
  container.replaceChildren();
  if (!state.jobs.length) container.append(node('p', '아직 분석한 영상이 없습니다. 첫 영상을 넣어 주세요.', 'note'));
  for (const job of [...state.jobs].sort((a, b) => b.created_at.localeCompare(a.created_at))) {
    const button = node('button', undefined, 'job');
    button.type = 'button';
    button.append(node('strong', job.name), node('small',
      `${jobNames[job.state]} · ${state.models.find(model => model.key === job.model)?.label || job.model}`));
    button.onclick = () => showJob(job.id).catch(e => error(e.message));
    container.append(button);
    if (['failed', 'interrupted'].includes(job.state)) {
      const retry = node('button', '보존된 원본으로 다시 분석');
      retry.type = 'button';
      retry.onclick = async () => {
        retry.disabled = true;
        try {
          const next = await api('/api/retry', {job_id: job.id});
          await refresh();
          await showJob(next.id);
        } catch (e) { error(e.message); }
        finally { retry.disabled = false; }
      };
      container.append(retry);
    }
  }
}

function captureISO() {
  const value = $('capturedAt').value;
  if (!value) return null;
  const offset = -new Date(value).getTimezoneOffset();
  return value + (value.length === 16 ? ':00' : '') + (offset >= 0 ? '+' : '-') +
    String(Math.floor(Math.abs(offset) / 60)).padStart(2, '0') + ':' + String(Math.abs(offset) % 60).padStart(2, '0');
}

$('provenance').onchange = () => {
  const needed = $('provenance').value === 'public_real';
  $('creditFields').hidden = !needed;
  for (const id of ['creditUrl', 'creditAuthor', 'creditLicense']) $(id).required = needed;
};
let targetBox = null, targetStart = null, targetURL = null;
const targetCanvas = $('targetCanvas');
const targetVideo = $('targetVideo');
function drawTarget() {
  if (!targetVideo.videoWidth || targetVideo.readyState < 2) return;
  const context = targetCanvas.getContext('2d');
  context.drawImage(targetVideo, 0, 0, targetCanvas.width, targetCanvas.height);
  if (targetBox) {
    const [x1, y1, x2, y2] = targetBox;
    context.strokeStyle = '#54f49b'; context.lineWidth = 3;
    context.strokeRect(x1 * targetCanvas.width, y1 * targetCanvas.height,
      (x2-x1) * targetCanvas.width, (y2-y1) * targetCanvas.height);
  }
}
function setTarget(box) {
  targetBox = box;
  ['targetLeft','targetTop','targetRight','targetBottom'].forEach((id, i) => {
    $(id).value = box ? (box[i] * 100).toFixed(1) : '';
  });
  $('targetStatus').textContent = box ? '첫 장면의 대상 지정됨. 이 영상에서만 사용합니다.' : '지정하지 않으면 자동 검출로 분석합니다.';
  drawTarget();
}
$('videoFile').onchange = () => {
  setTarget(null); targetStart = null;
  $('targetPreview').hidden = true;
  if (targetURL) URL.revokeObjectURL(targetURL);
  const file = $('videoFile').files[0];
  if (!file || file.size > 256 * 1024 * 1024) return;
  targetURL = URL.createObjectURL(file);
  targetVideo.src = targetURL;
};
targetVideo.onloadeddata = () => {
  targetCanvas.width = Math.min(800, targetVideo.videoWidth);
  targetCanvas.height = Math.round(targetCanvas.width * targetVideo.videoHeight / targetVideo.videoWidth);
  $('targetPreview').hidden = false;
  drawTarget();
};
targetVideo.onerror = () => {
  targetBox = null;
  $('targetStatus').textContent = '브라우저가 첫 장면을 읽지 못했습니다. 대상 지정 없이 자동 분석할 수 있습니다.';
};
function targetPoint(event) {
  const rect = targetCanvas.getBoundingClientRect();
  return [Math.max(0, Math.min(1, (event.clientX-rect.left)/rect.width)),
    Math.max(0, Math.min(1, (event.clientY-rect.top)/rect.height))];
}
targetCanvas.onpointerdown = event => {
  targetStart = targetPoint(event); targetCanvas.setPointerCapture(event.pointerId);
};
targetCanvas.onpointerup = event => {
  if (!targetStart) return;
  const end = targetPoint(event), start = targetStart; targetStart = null;
  const box = [Math.min(start[0],end[0]), Math.min(start[1],end[1]), Math.max(start[0],end[0]), Math.max(start[1],end[1])];
  if (box[2]-box[0] >= 0.01 && box[3]-box[1] >= 0.01) setTarget(box);
};
targetCanvas.onpointercancel = () => { targetStart = null; };
$('clearTarget').onclick = () => setTarget(null);
$('applyTarget').onclick = () => {
  const inputs = ['targetLeft','targetTop','targetRight','targetBottom'].map(id => $(id));
  const box = inputs.map(input => Number(input.value)/100);
  if (inputs.some(input => !input.value || !input.checkValidity()) || box[2] <= box[0] || box[3] <= box[1]) {
    $('targetStatus').textContent = '0–100% 범위에서 오른쪽 > 왼쪽, 아래쪽 > 위쪽으로 입력하세요.';
    return;
  }
  setTarget(box);
};
$('uploadForm').onsubmit = async event => {
  event.preventDefault();
  error('');
  const button = $('analyzeButton');
  button.disabled = true;
  try {
    const file = $('videoFile').files[0];
    if (!file) throw new Error('영상 파일을 선택하세요.');
    const initialTargetBox = targetBox ? [...targetBox] : null;
    if (file.size > 256 * 1024 * 1024) throw new Error('256MiB 이하의 원본 영상 구간을 선택하세요.');
    $('uploadStatus').textContent = '이 컴퓨터에 영상 저장 중…';
    const response = await fetch('/api/upload', {
      method: 'POST', body: file,
      headers: {'X-Lab-Token': state.token, 'X-Filename': encodeURIComponent(file.name), 'Content-Type': 'application/octet-stream'}
    });
    const upload = await response.json();
    if (!response.ok) throw new Error(upload.error);
    const zones = $('zones').checked ? {upper: [0, 0, 1, 1/3], middle: [0, 1/3, 1, 1/3], lower: [0, 2/3, 1, 1/3]} : {};
    const job = await api('/api/jobs', {
      upload_id: upload.id, model: $('model').value, provenance: $('provenance').value,
      target_box: initialTargetBox,
      credit: {url: $('creditUrl').value.trim(), author: $('creditAuthor').value.trim(),
        license: $('creditLicense').value.trim(), role: $('creditRole').value.trim()},
      window_seconds: Number($('window').value), zones,
      context: {animal_id: $('animal').value.trim(), camera_revision: $('camera').value.trim(),
        conditions: $('conditions').value.trim(), recording_id: $('recording').value.trim(), captured_at: captureISO()}
    });
    $('uploadStatus').textContent = '분석 대기열에 추가했습니다. 진행 상황은 오른쪽에서 확인하세요.';
    await refresh();
    await showJob(job.id);
  } catch (e) {
    error(e.message);
    $('uploadStatus').textContent = '추가하지 못했습니다.';
  } finally { button.disabled = false; }
};

async function showJob(id, selectedWindowId) {
  error('');
  const job = await api('/api/jobs/' + encodeURIComponent(id));
  currentJob = job;
  $('jobResult').hidden = job.state !== 'complete';
  if (job.state !== 'complete') {
    if (job.error) error(job.error);
    return;
  }
  $('jobTitle').textContent = job.name;
  $('jobOrigin').textContent = {real_camera: '직접 촬영 · 사용자 선언', public_real: '공개 실제 영상',
    synthetic_test: '합성 검사 영상', unverified_file: '출처 확인 전'}[job.provenance];
  const summary = job.summary;
  $('jobFacts').textContent = `원본 ${summary.source.duration_seconds.toFixed(1)}초 · 분석 ${summary.sampled_frames}개 표본 · ` +
    `추적 규칙을 통과한 표본 ${summary.observed_samples}개 (실제로 맞힌 수가 아님)`;
  $('reviewLegend').textContent = job.review_render_version >= 2 ? `주황 박스: 모델이 추측한 크레스티드 위치. 점수 ${summary.config.confidence.toFixed(2)} 이상만 표시하며 집계 기준과 같습니다. 번호는 박스 순번입니다. 동물·질병·이상을 확인했다는 뜻이 아닙니다.` : '이전 표시 방식의 영상입니다. 집계 기준보다 낮은 점수의 후보 박스도 표시되어 있습니다. 박스 수를 성능 수치와 직접 비교하지 마세요.';
  if (job.review_render_version >= 3) {
    $('reviewLegend').textContent = `주황 박스는 위치 예측입니다. T번호는 이 영상 안에서 이어진 추적 구간이며 실제 개체 신원은 아닙니다. pending은 연결 확인 중, ?는 겹침·점프로 연결이 불확실한 상태입니다. 점수 ${summary.config.confidence.toFixed(2)} 이상을 표시합니다. 긴 가림 뒤에는 새 번호를 부여하며 보이지 않는 동안의 움직임은 계산하지 않습니다.`;
    $('jobFacts').textContent += ` · 추적 구간 ${summary.tracking.segments_created}개 (동물 수 아님)`;
  }
  if (summary.target_selection_mode === 'initial_box_guided') {
    $('reviewLegend').textContent = '첫 장면에서 지정한 대상의 추적 결과입니다. 전체 자동 검출 후보 중 지정한 몸과 이어지는 후보만 표시합니다. T번호는 영상 안의 추적 구간입니다. 화면의 raw candidates는 필터링 전 후보 수이며, 이 모드의 박스 감소를 자동 검출 정확도 향상으로 계산하지 않습니다. 연결을 오래 놓치면 재지정이 필요합니다.';
  }
  if (summary.detector_backend === 'sam2-hybrid') {
    $('reviewLegend').textContent = '주황 박스는 모델이 추정한 동물 영역을 감싼 사각형입니다. T번호는 영상 안의 추적 구간이며 실제 개체 신원이 아닙니다. pending은 연결 확인 중입니다. 활동량·구역 체류·이상 판정은 보류합니다.';
  }
  $('jobCredit').replaceChildren();
  if (job.credit?.url) {
    $('jobCredit').append(node('span', `${job.credit.author} · ${job.credit.license} · `),
      sourceLink('원본 영상', job.credit.url), node('p', `${job.credit.role || ''} · ` +
        '검토 영상 변경: 표본 프레임 선택·박스 표시·H.264 변환. 검토 영상도 원본의 이용 조건을 따릅니다.'));
  }
  $('reviewTiming').textContent = `초당 최대 ${summary.config.sample_fps}장씩 분석한 검토 영상입니다. 재생 속도는 원본과 다를 수 있으며 아래 시각은 원본 기준입니다. 끊겨 보이는 재생 자체가 이상 행동은 아닙니다.`;
  $('reviewVideo').src = job.video;
  $('referenceVideo').hidden = true;
  $('referenceCaption').textContent = '';
  if (job.features.windows.length) {
    const index = job.features.windows.findIndex(row => row.window_id === selectedWindowId);
    selectWindow(Math.max(0, index));
  }
}

function renderTimeline() {
  $('timeline').replaceChildren();
  currentJob.features.windows.forEach((window, index) => {
    const compared = currentJob.comparison.windows[index];
    const button = node('button', `${window.start_seconds.toFixed(0)}–${window.end_seconds.toFixed(0)}초`, 'time-window');
    button.type = 'button';
    button.classList.add(compared.status === 'change_candidate' ? 'change_candidate' : window.quality);
    button.classList.toggle('selected', currentWindow?.window_id === window.window_id);
    button.onclick = () => selectWindow(index);
    $('timeline').append(button);
  });
}

function seekSource(video, job, seconds) {
  const row = job.observations.find(item => item.offset_seconds >= seconds) || job.observations.at(-1);
  if (!row) return;
  const offset = row.review_offset_seconds;
  if (video.readyState) video.currentTime = offset;
  else video.onloadedmetadata = () => { video.currentTime = offset; };
}

function selectWindow(index) {
  const window = currentJob.features.windows[index];
  currentWindow = window;
  const comparison = currentJob.comparison.windows[index];
  renderTimeline();
  seekSource($('reviewVideo'), currentJob, window.start_seconds);
  $('windowFacts').textContent = `원본 ${window.start_seconds.toFixed(1)}–${window.end_seconds.toFixed(1)}초 · ` +
    `추적 계산 가능 시간 ${(window.coverage * 100).toFixed(0)}% (정답 검출률 아님)` + (window.features ?
      ` · 박스 중심 이동 속도 ${window.features.speed.toFixed(4)} 화면 대각선/초 · 박스 이동 비율 ${(window.features.moving_fraction * 100).toFixed(0)}% (검출 흔들림 포함 가능)` : '');
  if (window.quality_reason === 'measurement_withheld') {
    $('windowFacts').textContent = `원본 ${window.start_seconds.toFixed(1)}–${window.end_seconds.toFixed(1)}초 · 위치와 추적 결과만 제공 · 활동량 계산 보류`;
  }
  $('windowReason').textContent = comparison.reason ? reasonNames[comparison.reason] :
    (comparison.status === 'change_candidate' ?
      `변화 후보 · 점수 ${comparison.score.toFixed(2)} / 기준 ${comparison.threshold.toFixed(2)}. 근거 영상을 검토하세요.` :
      '검토된 평소 기록 범위 안입니다. 건강 정상 판정은 아닙니다.');
  if (comparison.reason === 'insufficient_observation' && window.quality_reason) {
    const qualityReasons = {
      measurement_withheld: '이 분석 방식은 활동량과 구역 체류를 검증하지 않아 계산을 보류했습니다. 표시된 추적 결과를 이상 판정이나 정상 기준 학습에 사용하지 않습니다.',
      multiple_track_segments: '서로 다른 추적 구간이 섞여 있어 한 개체의 평소 기록으로 합치지 않았습니다.',
      low_coverage: '이어진 관측 시간이 부족해 비교를 보류했습니다. 안 보인 시간을 활동량 0으로 바꾸지 않습니다.',
      short_window: '영상 끝의 구간이 설정한 비교 길이보다 짧아 보류했습니다. 추적 실패나 이상 행동을 뜻하지 않습니다.'
    };
    $('windowReason').textContent = qualityReasons[window.quality_reason] || reasonNames.insufficient_observation;
  }
  const featureNames = {speed: '박스 중심 이동 속도', moving_fraction: '박스 이동 비율', x_span: '박스 중심의 가로 이동 범위', y_span: '박스 중심의 세로 이동 범위'};
  $('windowDifferences').textContent = comparison.differences ? '과거와 차이가 큰 항목: ' +
    Object.entries(comparison.differences).sort((a, b) => b[1] - a[1]).slice(0, 3)
      .map(([key, value]) => `${featureNames[key] || key} ${value.toFixed(2)}`).join(' · ') : '';
  $('assessment').value = window.assessment || 'uncertain';
  $('partition').value = window.partition || 'evaluation';
  if (window.reviewer && window.review_method === 'human') $('reviewer').value = window.reviewer;
  $('reviewStatus').textContent = window.reviewed_at ? `${window.review_method === 'human' ? '사람' : 'AI'} 검토가 저장되어 있습니다.` : '';
  const behaviorReview = window.behavior_review;
  const usableForBehavior = window.quality === 'usable';
  for (const option of $('behaviorState').options) {
    option.disabled = !usableForBehavior && option.value !== 'unobservable';
  }
  $('behaviorState').value = usableForBehavior ? (behaviorReview?.behavior || 'unobservable') : 'unobservable';
  if (behaviorReview?.reviewer) $('behaviorReviewer').value = behaviorReview.reviewer;
  else if ($('reviewer').value) $('behaviorReviewer').value = $('reviewer').value;
  $('behaviorStatus').textContent = behaviorReview ?
    (behaviorReview.behavior ? `사람이 ${behaviorReview.behavior === 'moving' ? '이동' : '휴식'}으로 저장했습니다.` : '사람이 관측 불가로 저장했습니다.') :
    (usableForBehavior ? '아직 행동 상태를 저장하지 않았습니다.' : '이 구간은 추적 품질이 부족해 관측 불가만 기록할 수 있습니다.');
  $('neighbors').replaceChildren();
  $('referenceVideo').hidden = true;
  $('referenceVideo').pause();
  $('referenceCaption').textContent = '';
  for (const neighbor of comparison.neighbors || []) {
    const button = node('button', `비슷한 과거 구간 · ${neighbor.captured_at} · ${neighbor.start_seconds.toFixed(0)}초`, 'neighbor');
    button.type = 'button';
    button.onclick = async () => {
      try {
        const past = await api('/api/jobs/' + neighbor.run_id);
        if (!past.video) throw new Error('과거 영상을 찾을 수 없습니다.');
        const video = $('referenceVideo');
        video.hidden = false;
        video.src = past.video;
        seekSource(video, past, neighbor.start_seconds);
        $('referenceCaption').textContent = `사람이 정상으로 검토한 비교 영상 · ${past.name}`;
      } catch (e) { error(e.message); }
    };
    $('neighbors').append(button);
  }
}

$('reviewVideo').ontimeupdate = () => {
  if (!currentJob?.observations) return;
  let row = currentJob.observations[0];
  for (const item of currentJob.observations) {
    if (item.review_offset_seconds > $('reviewVideo').currentTime) break;
    row = item;
  }
  const statuses = {observed: '추적 규칙 통과 · 실제 정답 미확인', no_confident_track: '신뢰 가능한 추적 없음',
    ambiguous_multiple_detections: '각 대상은 별도 추적 · 전체 이동량 합산 보류', implausible_track_jump: '추적 점프로 판단 보류',
    ambiguous_association: '겹침으로 동일 대상 연결 불확실', track_pending: '연속 검출 확인 중'};
  $('sourceTime').textContent = row ? `원본 시각 ${row.offset_seconds.toFixed(3)}초 · ${statuses[row.status] || '추적 불확실'}` : '';
  if (row?.target_selection) {
    const reasons = {seed_matched:'지정 대상 후보 연결', ambiguous_seed_candidates:'대상 후보가 겹쳐 보류',
      no_matching_seed_candidate:'이어지는 대상 후보 없음', seed_lost_requires_new_selection:'연결을 놓침 · 새 영상 구간에서 재지정 필요'};
    $('sourceTime').textContent += ` · ${reasons[row.target_selection]} · 원래 검출 후보 ${row.detector_candidates.length}개`;
  }
};

$('reviewForm').onsubmit = async event => {
  event.preventDefault();
  try {
    if (!currentWindow) throw new Error('구간을 선택하세요.');
    const windowId = currentWindow.window_id;
    const saved = await api('/api/review', {
      job_id: currentJob.id, window_id: windowId, assessment: $('assessment').value,
      review_method: 'human', reviewer: $('reviewer').value.trim(), partition: $('partition').value
    });
    await refresh();
    await showJob(currentJob.id, windowId);
    $('reviewStatus').textContent = saved.reference_invalidated ?
      '검토를 저장했습니다. 기존 기준에 쓰인 판단이 바뀌어 적용을 해제했습니다. 기준을 다시 만드세요.' :
      '검토를 저장했습니다. 기준은 자동으로 바뀌지 않습니다.';
  } catch (e) { error(e.message); }
};

$('behaviorReviewForm').onsubmit = async event => {
  event.preventDefault();
  try {
    if (!currentWindow) throw new Error('구간을 선택하세요.');
    const state = $('behaviorState').value;
    const observed = state !== 'unobservable';
    await api('/api/behavior-review', {
      job_id: currentJob.id, window_id: currentWindow.window_id,
      behavior: observed ? state : null,
      visibility: observed ? 'visible' : 'unobservable',
      certainty: observed ? 'certain' : 'uncertain',
      reviewer: $('behaviorReviewer').value.trim()
    });
    await refresh();
    await showJob(currentJob.id, currentWindow.window_id);
    $('behaviorStatus').textContent = observed ?
      '행동 상태를 저장했습니다. 실제 학습은 서로 다른 녹화 묶음의 사람 검토 라벨이 충분할 때만 시작합니다.' :
      '관측 불가를 저장했습니다. 이 구간은 휴식이나 학습 음성으로 바꾸지 않습니다.';
  } catch (e) { error(e.message); }
};

$('fitReference').onclick = async () => {
  error('');
  $('fitReference').disabled = true;
  try {
    const result = await api('/api/reference', {});
    await refresh();
    $('referenceState').textContent = `${result.contexts}개 조건에 평소 기록 ${result.references}구간, ` +
      `별도 보정 ${result.calibration}구간으로 기준을 만들었습니다. 미충족 조건 ${result.pending}개. 현장 성능은 아직 미검증입니다.`;
  } catch (e) { $('referenceState').textContent = '기준을 만들지 않았습니다. ' + e.message; }
  finally { $('fitReference').disabled = false; }
};

async function renderEvaluation() {
  const result = await api('/api/evaluation');
  $('evaluationState').textContent = result.evaluated_windows ?
    `평가 ${result.evaluated_windows}구간 · 이상 정탐 ${result.true_positive} · 오경보 ${result.false_positive} · 놓침 ${result.false_negative} · 정상 판정 ${result.true_negative} · 판단 보류 ${result.abstentions}. 이상 탐지율 ${result.recall === null ? '미측정' : (result.recall * 100).toFixed(1) + '%'}` :
    `사람이 검토한 평가용 구간 ${result.reviewed_windows}개. ${result.reference_available ? '조건과 날짜가 맞는 독립 평가 자료가 필요합니다.' : '학습된 개인 기준이 없어 이상탐지 성능은 미측정입니다.'}`;
}

function showVisualMemory() {
  const report = state.visual_memory_check;
  if (!report) return;
  const item = report.cases.find(row => row.key === $('visualMemorySource').value);
  if (!item) return;
  const modes = (report.variant_order || ['baseline', 'automatic', 'assisted']).filter(key => item.variants[key]);
  const preferred = $('visualMemoryMode').value || report.default_mode || 'automatic';
  $('visualMemoryMode').replaceChildren();
  for (const key of modes) {
    const data = item.variants[key];
    const option = node('option', data.label);
    option.value = key;
    $('visualMemoryMode').append(option);
  }
  if (item.variants[preferred]) $('visualMemoryMode').value = preferred;
  const variant = item.variants[$('visualMemoryMode').value];
  const video = $('visualMemoryVideo');
  video.pause();
  video.src = variant.video;
  $('visualMemoryMetrics').replaceChildren();
  for (const key of modes) {
    const data = item.variants[key];
    const metrics = data.uniform.metrics;
    const following = data.consecutive.following;
    const block = node('div');
    block.append(node('strong', data.label), node('p',
      `몸 위치 일치 ${metrics.true_positive}/${metrics.true_positive + metrics.false_negative}장 · 잘못 찾은 박스 ${metrics.false_positive}개. ` +
      `연속 두 장 모두 일치 ${following.both_body_matched_pairs}/${following.eligible_adjacent_pairs}쌍.`));
    $('visualMemoryMetrics').append(block);
  }
  $('visualMemoryMethod').textContent = variant.method;
  $('visualMemoryCredit').replaceChildren(node('span', `${item.author} · ${item.license} · `), sourceLink('영상 원문', item.source_url));
  function updateTime() {
    const position = Math.min(variant.timeline.length - 1, Math.max(0, Math.floor(video.currentTime * 3)));
    const row = variant.timeline[position];
    $('visualMemoryTime').textContent = row ?
      `원본 ${row.offset_seconds.toFixed(3)}초 · 프레임 ${row.frame_index}. 초당 최대 3장으로 만든 검토 영상입니다.` : '영상 시간 기록 없음';
  }
  video.ontimeupdate = updateTime;
  video.onloadedmetadata = updateTime;
  video.onerror = () => { $('visualMemoryTime').textContent = '결과 영상을 불러오지 못했습니다. 서버와 저장 파일을 확인하세요.'; };
  updateTime();
}

function renderVisualMemory() {
  const report = state.visual_memory_check;
  $('visualMemoryCase').hidden = !report?.cases?.length;
  if (!report?.cases?.length) return;
  const selected = $('visualMemorySource').value;
  $('visualMemorySource').replaceChildren();
  for (const item of report.cases) {
    const option = node('option', item.label);
    option.value = item.key;
    $('visualMemorySource').append(option);
  }
  if (report.cases.some(item => item.key === selected)) $('visualMemorySource').value = selected;
  $('visualMemoryMeaning').textContent = report.meaning;
  $('visualMemoryLimits').textContent = report.limitations;
  if (!$('visualMemoryVideo').getAttribute('src')) showVisualMemory();
}

$('visualMemorySource').onchange = showVisualMemory;
$('visualMemoryMode').onchange = showVisualMemory;

async function refresh() {
  state = await api('/api/state');
  renderJobs();
  renderVerification();
  renderVisualMemory();
  const videoReport = state.captive_experiment?.runs?.length ? state.captive_experiment : state.camera_experiment?.runs?.length ? state.camera_experiment : state.diversity_experiment?.runs?.length ? state.diversity_experiment : state.public_research;
  $('publicVideoCase').hidden = !videoReport?.runs?.length;
  if (videoReport?.runs?.length) {
    $('publicVideoMeaning').textContent = videoReport.video_summary;
    $('publicVideoLimits').textContent = videoReport.video_limitations;
    $('publicVideoRuns').replaceChildren();
    for (const run of videoReport.runs) {
      const item = node('div');
      item.append(node('strong', run.label), node('p', run.description));
      const button = node('button', '이 결과 영상 보기');
      button.type = 'button';
      button.onclick = () => showJob(run.job_id).catch(e => error(e.message));
      item.append(button);
      $('publicVideoRuns').append(item);
    }
  }
  $('trackingCase').hidden = !state.tracking_check;
  if (state.tracking_check) {
    const report = state.tracking_check;
    $('trackingMeaning').textContent = report.meaning;
    $('trackingResults').replaceChildren();
    for (const run of report.runs) {
      const item = node('div');
      item.append(node('strong', run.label), node('p', run.description));
      const button = node('button', '이 방식의 영상 보기');
      button.type = 'button'; button.onclick = () => showJob(run.job_id).catch(e => error(e.message));
      item.append(button); $('trackingResults').append(item);
    }
    $('trackingLimits').textContent = report.limitations;
  }
  const input = state.camera_input;
  $('connectionState').textContent = input.mode === 'finalized_file' ?
    '자동 파일 수신 설정 · 현장 성능 미검증' : '수동 영상 입력 · 카메라 미연결';
  $('cameraState').textContent = input.mode === 'finalized_file' ?
    `완성된 파일을 자동 수신합니다. 마지막 수신: ${input.last_received_at || '아직 없음'} · ` +
    `입력 오류 ${input.pending_file_errors || 0}개. 실제 카메라 연결 상태를 뜻하지 않습니다.` :
    '현재는 직접 영상 파일을 넣는 방식입니다. Pi 카메라 설치 후 자동 파일 수신을 설정할 수 있습니다.';
  if (state.reference) $('referenceState').textContent = '저장된 비교 기준이 있습니다. 새 조건·새 날짜의 영상에서 검증하세요.';
}

async function init() {
  await refresh();
  $('photoCount').textContent = state.images.length;
  $('splitCounts').textContent = ['train', 'val', 'test'].map(split => state.images.filter(row => row.split === split).length).join(' / ');
  $('humanCount').textContent = `${state.images.filter(row => row.review_method === 'human').length}장`;
  $('datasetNote').textContent = `전체 ${state.images.length}장은 현재 실험 자료입니다. 기존 기준 모델은 이전 27장, 이전 오검출 감소 후보는 42장으로 학습했습니다. 새로 추가한 사진이 기존 모델에 자동 반영되지는 않습니다. 초록 기준 박스는 AI 검토를 포함하므로 틀릴 수 있습니다.`;
  if (state.training_experiment) {
    const experiment = state.training_experiment;
    $('trainingOutcome').textContent = `${experiment.training_images}장으로 추가 학습 완료. 같은 개발 사진 ${experiment.validation_images}장에서 ` + experiment.models.map(model => `${model.label}: 놓침 ${model.false_negative}개 / 오검출 ${model.false_positive}개`).join(' · ') + `. ${experiment.decision} AI 기준 라벨에 대한 개발 결과이며 현장 성능은 미검증입니다.`;
  }
  for (const option of $('split').options) {
    if (option.value !== 'all') option.textContent = `${splitNames[option.value]} ${state.images.filter(row => row.split === option.value).length}장`;
  }
  for (const model of state.models) {
    const option = node('option', model.label + (model.available === false ? ' · MPS 모드 필요' : ''));
    option.value = model.key;
    option.disabled = model.available === false;
    $('model').append(option);
  }
  const availableCollections = new Set(state.images.map(row => row.collection || 'crested'));
  if (!availableCollections.has($('collection').value)) {
    $('collection').value = ['captive', 'camera', 'expanded', 'public', 'crested'].find(key => availableCollections.has(key)) || 'crested';
  }
  const selectedCandidate = state.camera_experiment?.validation?.selected;
  const preferredModel = selectedCandidate === 'camera-adapted' ? 'camera_lizard' :
    selectedCandidate === 'baseline' || state.diversity_experiment?.validation?.selected === 'diverse-full' ? 'diverse_lizard' : null;
  if (state.models.some(model => model.key === preferredModel)) $('model').value = preferredModel;
  describeModel();
  gallery();
  setInterval(async () => {
    if (document.hidden) return;
    try {
      const watching = state.camera_input.mode === 'finalized_file';
      const running = state.jobs.some(job => ['queued', 'running'].includes(job.state));
      if (!running && !watching) return;
      const selected = currentJob?.id;
      const wasPending = currentJob && currentJob.state !== 'complete';
      await refresh();
      if (selected && wasPending && state.jobs.some(job => job.id === selected && job.state === 'complete')) await showJob(selected);
    } catch (e) { error('서버 연결이 끊겼습니다. 원본과 저장된 검토는 보존됩니다.'); }
  }, 2500);
}
init().catch(e => error(e.message));
