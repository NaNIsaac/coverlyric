"use strict";

const $ = (id) => document.getElementById(id);
const FRAME_W = 1920;
const FRAME_H = 1080;
const DEFAULT_PLACES = {
  album_x: 0, album_y: 0, album_scale: 1,
  panel_x: 0, panel_y: 0, panel_scale: 1,
  title_x: 0, title_y: 0, title_scale: 1,
  bar_x: 0, bar_y: 0, bar_scale: 1,
};
const NAMES = { album: "앨범", panel: "가사", title: "제목", bar: "재생 바" };

let state = null;
let diff = [];
let tapIndex = -1;
let syncTimer = null;
let syncing = false;
let again = false;
let lastBoxes = {};
let dragging = false;

function toast(text, ms = 3500) {
  const t = $("toast");
  t.textContent = text;
  t.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.classList.remove("show"), ms);
}

async function api(path, options = {}) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let message = `오류 (${res.status})`;
    try { message = (await res.json()).error || message; } catch (e) { /* not JSON */ }
    throw new Error(message);
  }
  return res;
}

function clock(seconds) {
  if (seconds == null || Number.isNaN(seconds)) return "";
  const s = Math.max(0, seconds);
  const m = Math.floor(s / 60);
  return `${m}:${(s - m * 60).toFixed(2).padStart(5, "0")}`;
}

function parseClock(text) {
  const m = String(text).trim().match(/^(?:(\d+):)?(\d+(?:\.\d+)?)$/);
  if (!m) return null;
  return (m[1] ? Number(m[1]) * 60 : 0) + Number(m[2]);
}

function payload() {
  return { title: state.title, artist: state.artist, lines: state.lines, style: state.style };
}

function scheduleSync(delay = 150) {
  clearTimeout(syncTimer);
  syncTimer = setTimeout(sync, delay);
}

async function sync() {
  if (!state) return;
  if (syncing) { again = true; return; }
  syncing = true;
  try {
    if (!state.has_art) {
      await api("/api/state", { method: "POST", body: JSON.stringify(payload()) });
      $("stage-empty").hidden = false;
      $("still").hidden = true;
      $("boxes").innerHTML = "";
    } else {
      const t = Number($("time").value);
      const w = Math.round($("stage").clientWidth * (window.devicePixelRatio || 1));
      const res = await api(`/api/preview?t=${t}&w=${w}`, { method: "POST", body: JSON.stringify(payload()) });
      // A change made while this still was drawn makes it stale: skip it and fetch again. During a drag
      // the release fetches anyway, and redrawing the boxes would drop the one under the pointer.
      if (again || dragging) return;
      const blob = await res.blob();
      const old = $("still").src;
      $("still").src = URL.createObjectURL(blob);
      if (old.startsWith("blob:")) URL.revokeObjectURL(old);
      $("still").hidden = false;
      $("stage-empty").hidden = true;
      lastBoxes = JSON.parse(res.headers.get("X-Boxes") || "{}");
      drawBoxes();
    }
  } catch (e) {
    toast(e.message);
  } finally {
    syncing = false;
    if (again) { again = false; sync(); }
  }
}

function drawBoxes() {
  const holder = $("boxes");
  holder.innerHTML = "";
  for (const [name, b] of Object.entries(lastBoxes)) {
    const el = document.createElement("div");
    el.className = "box";
    el.dataset.el = name;
    placeBox(el, b);
    el.innerHTML = `<span class="tag">${NAMES[name]}</span><span class="grip" title="끌어서 크기 바꾸기"></span>`;
    el.addEventListener("pointerdown", (ev) => startDrag(ev, el, name, b));
    holder.appendChild(el);
  }
}

function placeBox(el, b) {
  el.style.left = `${(b[0] / FRAME_W) * 100}%`;
  el.style.top = `${(b[1] / FRAME_H) * 100}%`;
  el.style.width = `${((b[2] - b[0]) / FRAME_W) * 100}%`;
  el.style.height = `${((b[3] - b[1]) / FRAME_H) * 100}%`;
}

function startDrag(ev, el, name, box) {
  ev.preventDefault();
  const resize = ev.target.classList.contains("grip");
  const stage = $("stage").getBoundingClientRect();
  const k = FRAME_W / stage.width;
  const x0 = ev.clientX;
  const y0 = ev.clientY;
  const s = state.style;
  const start = { x: s[`${name}_x`], y: s[`${name}_y`], scale: s[`${name}_scale`] };
  const w0 = box[2] - box[0];
  dragging = true;
  el.appendChild(snapshot(box));
  el.classList.add("dragging");
  el.setPointerCapture(ev.pointerId);
  const move = (e) => {
    const dx = (e.clientX - x0) * k;
    const dy = (e.clientY - y0) * k;
    if (resize) {
      const scale = Math.min(2, Math.max(0.3, start.scale * (w0 + dx) / w0));
      s[`${name}_scale`] = Math.round(scale * 100) / 100;
      const grow = (scale / start.scale) - 1;
      placeBox(el, [box[0] - (w0 * grow) / 2, box[1] - ((box[3] - box[1]) * grow) / 2,
        box[2] + (w0 * grow) / 2, box[3] + ((box[3] - box[1]) * grow) / 2]);
    } else {
      s[`${name}_x`] = Math.round(start.x + dx);
      s[`${name}_y`] = Math.round(start.y + dy);
      placeBox(el, [box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy]);
    }
    fillPlaces();
  };
  const up = () => {
    dragging = false;
    el.classList.remove("dragging");
    el.removeEventListener("pointermove", move);
    el.removeEventListener("pointerup", up);
    scheduleSync(0);
  };
  el.addEventListener("pointermove", move);
  el.addEventListener("pointerup", up);
}

// The element's part of the last still, so it moves and grows with the pointer before the new still arrives.
function snapshot(box) {
  const still = $("still");
  const k = still.naturalWidth / FRAME_W;
  const canvas = document.createElement("canvas");
  canvas.className = "ghost";
  canvas.width = Math.max(1, Math.round((box[2] - box[0]) * k));
  canvas.height = Math.max(1, Math.round((box[3] - box[1]) * k));
  canvas.getContext("2d").drawImage(still, box[0] * k, box[1] * k, canvas.width, canvas.height,
    0, 0, canvas.width, canvas.height);
  return canvas;
}

const crop = { file: null, w: 0, h: 0, x: 0, y: 0, side: 0 };

function openCrop(file) {
  if (!file) return;
  const img = $("crop-img");
  const url = URL.createObjectURL(file);
  img.onload = () => {
    crop.file = file;
    crop.w = img.naturalWidth;
    crop.h = img.naturalHeight;
    crop.side = Math.min(crop.w, crop.h);
    crop.x = (crop.w - crop.side) / 2;
    crop.y = (crop.h - crop.side) / 2;
    $("crop-zoom").value = 1;
    $("crop").showModal();
    placeCrop();
  };
  img.onerror = () => { URL.revokeObjectURL(url); toast("이 그림은 열 수 없어요. png나 jpg를 골라 주세요."); };
  const old = img.src;
  img.src = url;
  if (old.startsWith("blob:")) URL.revokeObjectURL(old);
}

function clampCrop() {
  const most = Math.min(crop.w, crop.h);
  crop.side = Math.min(most, Math.max(most / 4, crop.side));
  crop.x = Math.min(crop.w - crop.side, Math.max(0, crop.x));
  crop.y = Math.min(crop.h - crop.side, Math.max(0, crop.y));
}

function placeCrop() {
  clampCrop();
  const k = $("crop-img").clientWidth / crop.w;
  const box = $("crop-box").style;
  box.left = `${crop.x * k}px`;
  box.top = `${crop.y * k}px`;
  box.width = box.height = `${crop.side * k}px`;
  $("crop-zoom").value = Math.min(crop.w, crop.h) / crop.side;
}

function dragCrop(ev) {
  ev.preventDefault();
  const resize = ev.target.classList.contains("grip");
  const k = crop.w / $("crop-img").clientWidth;
  const x0 = ev.clientX;
  const y0 = ev.clientY;
  const start = { ...crop };
  const el = $("crop-box");
  el.setPointerCapture(ev.pointerId);
  const move = (e) => {
    const dx = (e.clientX - x0) * k;
    const dy = (e.clientY - y0) * k;
    if (resize) {
      crop.side = start.side + Math.max(dx, dy);
      crop.side = Math.min(crop.side, crop.w - start.x, crop.h - start.y);
    } else {
      crop.x = start.x + dx;
      crop.y = start.y + dy;
    }
    placeCrop();
  };
  const up = () => {
    el.removeEventListener("pointermove", move);
    el.removeEventListener("pointerup", up);
  };
  el.addEventListener("pointermove", move);
  el.addEventListener("pointerup", up);
}

function zoomCrop(zoom) {
  const cx = crop.x + crop.side / 2;
  const cy = crop.y + crop.side / 2;
  crop.side = Math.min(crop.w, crop.h) / zoom;
  crop.x = cx - crop.side / 2;
  crop.y = cy - crop.side / 2;
  placeCrop();
}

async function finishCrop() {
  const side = Math.round(crop.side);
  const out = Math.min(side, 2400);
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = out;
  canvas.getContext("2d").drawImage($("crop-img"), Math.round(crop.x), Math.round(crop.y), side, side, 0, 0, out, out);
  const blob = await new Promise((done) => canvas.toBlob(done, "image/jpeg", 0.95));
  $("crop").close();
  const stem = crop.file.name.replace(/\.[^.]+$/, "");
  await upload("art", new File([blob], `${stem}.jpg`, { type: "image/jpeg" }));
}

function fillPlaces() {
  for (const tr of document.querySelectorAll(".places tr[data-el]")) {
    for (const input of tr.querySelectorAll("input")) {
      const key = `${tr.dataset.el}_${input.dataset.k}`;
      if (document.activeElement !== input) input.value = state.style[key];
    }
  }
}

function fillLook() {
  const s = state.style;
  for (const r of document.querySelectorAll('input[name="layout"]')) r.checked = r.value === s.layout;
  $("spin").checked = s.spin > 0;
  $("show_cd").checked = s.show_cd;
  $("spin").disabled = !s.show_cd || s.layout !== "case";
  $("show_cd").disabled = s.layout !== "case";
  $("band").value = s.band;
  $("blur").value = s.blur;
  $("dim").value = s.dim;
  $("show_title").checked = s.show_title;
  $("bar").checked = s.bar;
  fillPlaces();
  const select = $("font");
  if (![...select.options].some((o) => o.value === s.font)) {
    const o = new Option(s.font.split(/[\\/]/).pop(), s.font);
    select.add(o);
  }
  select.value = s.font;
}

function fillAll() {
  $("title").value = state.title;
  $("artist").value = state.artist;
  $("audio-name").textContent = state.has_audio ? `${clock(state.duration).replace(/\.\d+$/, "")} 길이의 노래` : "아직 없어요";
  $("art-name").textContent = state.has_art ? "표지 있음" : "정사각형 그림이 좋아요";
  if (state.has_audio) $("player").src = `/media/audio?v=${Date.now()}`;
  else $("player").removeAttribute("src");
  $("time").max = Math.max(1, state.duration || 60);
  fillLook();
  drawLines();
  scheduleSync(0);
}

function drawLines() {
  const holder = $("lines");
  holder.innerHTML = "";
  state.lines.forEach(([t, text], i) => {
    const row = document.createElement("div");
    row.className = "line";
    if (i === tapIndex) row.classList.add("next");
    if (diff[i] != null) row.classList.add("differs");
    row.innerHTML = `
      <span class="n">${i + 1}</span>
      <input class="t" type="text" value="${t == null ? "" : clock(t)}" placeholder="시간">
      <button class="quiet" data-a="minus" title="0.1초 빠르게">−0.1</button>
      <button class="quiet" data-a="plus" title="0.1초 늦게">+0.1</button>
      <button class="quiet" data-a="play" title="이 줄부터 듣기">▶</button>
      <input class="x" type="text">
      <button class="quiet" data-a="del" title="이 줄 지우기">✕</button>`;
    row.querySelector(".x").value = text;
    if (diff[i] != null) {
      const mine = document.createElement("div");
      mine.className = "mine";
      mine.textContent = diff[i] ? `내 가사: ${diff[i]}` : "내 가사에 없는 줄";
      if (diff[i]) {
        const use = document.createElement("button");
        use.className = "quiet";
        use.textContent = "내 가사로";
        use.onclick = () => { state.lines[i][1] = diff[i]; diff[i] = null; drawLines(); scheduleSync(); };
        mine.append(" ", use);
      }
      row.appendChild(mine);
    }
    row.querySelector(".t").addEventListener("change", (e) => {
      const v = e.target.value.trim() === "" ? null : parseClock(e.target.value);
      if (e.target.value.trim() !== "" && v == null) { toast("시간은 1:23.45 처럼 써 주세요."); return; }
      state.lines[i][0] = v;
      scheduleSync();
    });
    row.querySelector(".x").addEventListener("change", (e) => { state.lines[i][1] = e.target.value; scheduleSync(); });
    row.addEventListener("click", (e) => {
      const a = e.target.dataset && e.target.dataset.a;
      if (!a) return;
      if (a === "minus" || a === "plus") {
        if (state.lines[i][0] == null) return;
        state.lines[i][0] = Math.max(0, Math.round((state.lines[i][0] + (a === "plus" ? 0.1 : -0.1)) * 100) / 100);
        row.querySelector(".t").value = clock(state.lines[i][0]);
        showAt(state.lines[i][0] + 0.3);
      } else if (a === "play") {
        const p = $("player");
        p.currentTime = Math.max(0, (state.lines[i][0] || 0) - 1);
        p.play();
      } else if (a === "del") {
        state.lines.splice(i, 1);
        diff.splice(i, 1);
        drawLines();
        scheduleSync();
      }
    });
    holder.appendChild(row);
  });
  const timed = state.lines.filter(([t]) => t != null).length;
  $("check").textContent = state.lines.length ? `가사 ${state.lines.length}줄 중 ${timed}줄에 시간이 있어요.` : "";
}

function showAt(t) {
  $("time").value = t;
  $("time-label").textContent = clock(t).replace(/\.\d+$/, "");
  scheduleSync();
}

async function upload(kind, file) {
  if (!file) return;
  toast(`${file.name} 넣는 중...`);
  try {
    const res = await api(`/api/upload?kind=${kind}`, {
      method: "POST",
      headers: { "X-Name": encodeURIComponent(file.name) },
      body: file,
    });
    state = await res.json();
    if (kind === "font") await loadFonts();
    fillAll();
    toast("넣었어요.");
  } catch (e) {
    toast(e.message);
  }
}

async function loadFonts() {
  const data = await (await api("/api/fonts")).json();
  const select = $("font");
  select.innerHTML = "";
  const groups = [["함께 들어 있는 글꼴", data.bundled], ["이 컴퓨터의 글꼴", data.installed]];
  for (const [label, list] of groups) {
    if (!list.length) continue;
    const g = document.createElement("optgroup");
    g.label = label;
    for (const f of list) g.appendChild(new Option(f.name, f.id));
    select.appendChild(g);
  }
}

async function importText(name, text) {
  const res = await api("/api/import", {
    method: "POST",
    headers: { "X-Name": encodeURIComponent(name) },
    body: text,
  });
  const data = await res.json();
  state.lines = data.lines;
  diff = data.diff;
  tapIndex = -1;
  drawLines();
  scheduleSync();
  const bad = diff.filter((d) => d != null).length;
  const sung = data.lines.filter(([, x]) => x).length;
  if (data.own && bad) {
    toast(`${sung}줄을 넣었어요. 내 가사와 다른 줄 ${bad}개는 빨간 테두리로 표시했어요.`, 6000);
  } else if (data.own && sung !== data.own) {
    toast(`${sung}줄을 넣었어요. 내 가사는 ${data.own}줄이에요. 확인해 주세요.`, 6000);
  } else {
    toast(`${sung}줄을 넣었어요.`);
  }
}

function setTab(name) {
  for (const b of document.querySelectorAll(".tab")) b.classList.toggle("active", b.dataset.tab === name);
  for (const body of document.querySelectorAll(".tab-body")) body.hidden = body.dataset.body !== name;
  if (name === "ai") refreshPrompt();
}

async function refreshPrompt() {
  await api("/api/state", { method: "POST", body: JSON.stringify(payload()) });
  const data = await (await api("/api/prompt")).json();
  $("prompt").value = data.lines ? data.prompt : "먼저 2단계에서 가사를 넣어 주세요.";
}

function tapNextLabel() {
  if (tapIndex < 0) { $("tap-next").textContent = ""; return; }
  if (tapIndex >= state.lines.length) { $("tap-next").textContent = "끝까지 맞췄어요! 아래 목록에서 다듬어 보세요."; return; }
  $("tap-next").textContent = `다음 줄: ${state.lines[tapIndex][1] || "(빈 줄)"}`;
}

function tap() {
  if (tapIndex < 0 || tapIndex >= state.lines.length) return;
  state.lines[tapIndex][0] = Math.round($("player").currentTime * 100) / 100;
  tapIndex += 1;
  drawLines();
  tapNextLabel();
  if (tapIndex >= state.lines.length) stopTap();
  scheduleSync(600);
}

function stopTap() {
  $("tap-now").disabled = true;
  $("tap-stop").disabled = true;
  if (tapIndex < state.lines.length) $("player").pause();
  tapIndex = -1;
  drawLines();
}

async function pollRender() {
  try {
    const job = await (await api("/api/render")).json();
    if (job.state === "running") {
      $("progress").hidden = false;
      $("done").hidden = true;
      $("make").disabled = true;
      const share = job.total ? job.done / job.total : 0;
      $("progress-bar").value = share;
      const left = job.eta != null ? ` · 남은 시간 약 ${Math.max(1, Math.round(job.eta / 60))}분` : " · 시간을 재는 중";
      $("progress-text").textContent = `${Math.round(share * 100)}%${left}`;
      setTimeout(pollRender, 1000);
      return;
    }
    $("progress").hidden = true;
    $("make").disabled = false;
    if (job.state === "done") {
      $("done").hidden = false;
      $("done-name").textContent = job.out.split(/[\\/]/).pop();
    } else if (job.state === "error") {
      toast(`영상을 만들지 못했어요: ${job.message}`, 9000);
    }
  } catch (e) {
    toast(e.message);
  }
}

function bind() {
  $("audio-file").addEventListener("change", (e) => upload("audio", e.target.files[0]));
  $("art-file").addEventListener("change", (e) => { openCrop(e.target.files[0]); e.target.value = ""; });
  $("crop-box").addEventListener("pointerdown", dragCrop);
  $("crop-box").addEventListener("keydown", (e) => {
    const step = Math.min(crop.w, crop.h) / 50;
    const moves = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
    if (!moves[e.key]) return;
    e.preventDefault();
    crop.x += moves[e.key][0];
    crop.y += moves[e.key][1];
    placeCrop();
  });
  $("crop-zoom").addEventListener("input", (e) => zoomCrop(Number(e.target.value)));
  $("crop-cancel").addEventListener("click", () => $("crop").close());
  $("crop-ok").addEventListener("click", () => finishCrop().catch((e) => toast(e.message)));
  window.addEventListener("resize", () => { if ($("crop").open) placeCrop(); });
  $("font-file").addEventListener("change", (e) => upload("font", e.target.files[0]));
  $("title").addEventListener("input", (e) => { state.title = e.target.value; scheduleSync(500); });
  $("artist").addEventListener("input", (e) => { state.artist = e.target.value; scheduleSync(500); });

  $("lyrics-apply").addEventListener("click", async () => {
    const text = $("lyrics-text").value;
    if (!text.trim()) { toast("가사를 먼저 붙여 넣어 주세요."); return; }
    if (state.lines.some(([t]) => t != null) && !confirm("지금 목록의 시간이 지워져요. 새 가사로 바꿀까요?")) return;
    const res = await api("/api/import", { method: "POST", headers: { "X-Name": "lyrics.txt" }, body: text });
    state.lines = (await res.json()).lines;
    diff = [];
    drawLines();
    scheduleSync();
    $("step-timing").open = true;
    toast(`${state.lines.length}줄을 넣었어요. 이제 3단계에서 타이밍을 맞추세요.`);
  });

  for (const b of document.querySelectorAll(".tab")) b.addEventListener("click", () => setTab(b.dataset.tab));

  $("tap-start").addEventListener("click", () => {
    if (!state.has_audio) { toast("먼저 노래 파일을 넣어 주세요."); return; }
    if (!state.lines.length) { toast("먼저 2단계에서 가사를 넣어 주세요."); return; }
    tapIndex = 0;
    diff = [];
    $("tap-now").disabled = false;
    $("tap-stop").disabled = false;
    const p = $("player");
    p.currentTime = 0;
    p.play();
    drawLines();
    tapNextLabel();
    $("tap-now").focus();
  });
  $("tap-now").addEventListener("click", tap);
  $("tap-stop").addEventListener("click", () => { stopTap(); tapNextLabel(); });
  document.addEventListener("keydown", (e) => {
    if (tapIndex < 0) return;
    const typing = ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName);
    if ((e.code === "Space" || e.code === "Enter") && !typing) {
      e.preventDefault();
      tap();
    }
  });

  $("prompt-copy").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText($("prompt").value);
      toast("복사했어요. 채팅 AI에 노래 파일과 함께 붙여 넣으세요.");
    } catch (e) {
      $("prompt").select();
      toast("Ctrl+C 를 눌러 복사하세요.");
    }
  });
  $("answer-apply").addEventListener("click", async () => {
    const text = $("answer").value;
    if (!text.trim()) { toast("AI의 답을 먼저 붙여 넣어 주세요."); return; }
    try { await importText("answer.srt", text); } catch (e) { toast(e.message); }
  });
  $("timing-file").addEventListener("change", async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    try { await importText(f.name, await f.text()); } catch (err) { toast(err.message); }
    e.target.value = "";
  });

  $("line-add").addEventListener("click", () => {
    state.lines.push([null, ""]);
    drawLines();
    const rows = $("lines").querySelectorAll(".line .x");
    rows[rows.length - 1].focus();
  });

  for (const r of document.querySelectorAll('input[name="layout"]')) {
    r.addEventListener("change", () => { state.style.layout = r.value; fillLook(); scheduleSync(0); });
  }
  $("spin").addEventListener("change", (e) => { state.style.spin = e.target.checked ? 7 : 0; scheduleSync(0); });
  $("show_cd").addEventListener("change", (e) => { state.style.show_cd = e.target.checked; fillLook(); scheduleSync(0); });
  $("font").addEventListener("change", (e) => { state.style.font = e.target.value; scheduleSync(0); });
  $("band").addEventListener("input", (e) => { state.style.band = e.target.value; scheduleSync(); });
  $("blur").addEventListener("input", (e) => { state.style.blur = Number(e.target.value); scheduleSync(); });
  $("dim").addEventListener("input", (e) => { state.style.dim = Number(e.target.value); scheduleSync(); });
  $("show_title").addEventListener("change", (e) => { state.style.show_title = e.target.checked; scheduleSync(0); });
  $("bar").addEventListener("change", (e) => { state.style.bar = e.target.checked; scheduleSync(0); });
  for (const tr of document.querySelectorAll(".places tr[data-el]")) {
    for (const input of tr.querySelectorAll("input")) {
      input.addEventListener("change", () => {
        const v = Number(input.value);
        if (Number.isNaN(v)) return;
        state.style[`${tr.dataset.el}_${input.dataset.k}`] = v;
        scheduleSync(0);
      });
    }
  }
  $("reset-look").addEventListener("click", () => {
    Object.assign(state.style, DEFAULT_PLACES);
    fillPlaces();
    scheduleSync(0);
  });

  $("time").addEventListener("input", (e) => showAt(Number(e.target.value)));
  $("time-now").addEventListener("click", () => showAt($("player").currentTime));

  $("make").addEventListener("click", async () => {
    const untimed = state.lines.findIndex(([t]) => t == null);
    if (untimed >= 0) {
      toast(`${untimed + 1}번째 줄에 시간이 없어요. 3단계에서 맞춰 주세요.`, 6000);
      $("step-timing").open = true;
      return;
    }
    const minutes = Math.max(1, Math.round((state.duration || 60) / 60));
    if (!confirm(`지금 미리보기 모양 그대로 영상을 만들까요?\n${minutes}~${minutes * 2}분쯤 걸려요.`)) return;
    try {
      await api("/api/state", { method: "POST", body: JSON.stringify(payload()) });
      await api("/api/render", { method: "POST" });
      pollRender();
    } catch (e) {
      toast(e.message, 6000);
    }
  });
  $("make-stop").addEventListener("click", async () => {
    if (!confirm("영상 만들기를 그만둘까요?")) return;
    await api("/api/render/stop", { method: "POST" });
  });
  $("open-folder").addEventListener("click", () => api("/api/open", { method: "POST" }));

  $("demo").addEventListener("click", async () => {
    if (state.has_audio && !confirm("지금 작업 대신 데모 노래를 불러올까요?")) return;
    state = await (await api("/api/demo", { method: "POST" })).json();
    diff = [];
    $("lyrics-text").value = state.lines.map(([, x]) => x).join("\n");
    fillAll();
    $("step-look").open = true;
  });
  $("new").addEventListener("click", async () => {
    if (!confirm("지금 작업을 지우고 새로 시작할까요? 만든 영상은 지워지지 않아요.")) return;
    try {
      state = await (await api("/api/new", { method: "POST" })).json();
      diff = [];
      $("lyrics-text").value = "";
      fillAll();
    } catch (e) {
      toast(e.message);
    }
  });
  $("quit").addEventListener("click", async () => {
    if (!confirm("프로그램을 끝낼까요? 작업은 저장돼 있어요.")) return;
    await api("/api/quit", { method: "POST" });
    document.body.innerHTML = "<p style='padding:40px;font-size:20px'>끝났어요. 이 창을 닫아도 돼요.</p>";
  });
}

async function boot() {
  bind();
  await loadFonts();
  state = await (await api("/api/state")).json();
  $("lyrics-text").value = state.lines.map(([, x]) => x).join("\n");
  fillAll();
  pollRender();
  const params = new URLSearchParams(location.search);
  if (params.get("t")) showAt(Number(params.get("t")));
  const step = params.get("step");
  if (step && $(step)) {
    for (const d of document.querySelectorAll(".step")) d.open = d.id === step;
    if (params.get("tab")) setTab(params.get("tab"));
  }
}

boot().catch((e) => toast(e.message));
