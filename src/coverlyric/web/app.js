"use strict";

const $ = (id) => document.getElementById(id);
const FRAME_W = 1920;
const FRAME_H = 1080;
const DEFAULT_PLACES = {
  album_x: 0, album_y: 0, album_scale: 1,
  panel_x: 0, panel_y: 0, panel_scale: 1,
  title_x: 0, title_y: 0, title_scale: 1,
  bar_x: 0, bar_y: 0, bar_scale: 1,
  anim_x: 0, anim_y: 0, anim_scale: 1,
};
const NAMES = { album: "앨범", panel: "가사", title: "제목", bar: "재생 바", anim: "움직이는 그림" };

let state = null;
let diff = [];
let notes = {};
let tapIndex = -1;
let tapUndo = [];
let syncTimer = null;
let syncing = false;
let again = false;
let lastBoxes = {};
let dragging = false;

function toast(text, ms = 3500, action = null) {
  const t = $("toast");
  t.textContent = text;
  if (action) {
    const b = document.createElement("button");
    b.textContent = action.label;
    b.addEventListener("click", () => { t.classList.remove("show"); action.run(); });
    t.append(b);
  }
  t.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.classList.remove("show"), ms);
}

async function api(path, options = {}) {
  // The server takes a POST only as JSON or as an upload with its name header.
  if (options.method === "POST" && !(options.headers && options.headers["X-Name"])) {
    options = { ...options, headers: { ...options.headers, "Content-Type": "application/json" } };
  }
  const res = await fetch(path, options);
  if (!res.ok) {
    let message = `오류 (${res.status})`;
    try { message = (await res.json()).error || message; } catch (e) { /* not JSON */ }
    throw new Error(message);
  }
  return res;
}

function payload() {
  return { title: state.title, artist: state.artist, lines: state.lines, style: state.style, anim: state.anim };
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
  img.onerror = () => { URL.revokeObjectURL(url); toast("이 그림을 열 수 없습니다. png 또는 jpg 파일을 고르세요."); };
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

// A GIF is the whole moving picture and keeps its own speed; images are frames shown at anim_fps.
function drawAnim() {
  const list = state.anim || [];
  const gif = list.some((name) => name.toLowerCase().endsWith(".gif"));
  $("anim-panel").hidden = !list.length;
  document.querySelector('.places tr[data-el="anim"]').hidden = !list.length;
  $("anim-fps-row").hidden = gif || list.length < 2;
  $("anim_fps").value = state.style.anim_fps;
  $("anim-fps-label").textContent = state.style.anim_fps;
  $("anim_above").checked = state.style.anim_above;
  const holder = $("anim-list");
  holder.innerHTML = "";
  list.forEach((name, i) => {
    const li = document.createElement("li");
    li.innerHTML = `
      <span class="n">${i + 1}</span>
      <img alt="" loading="lazy">
      <span class="name"></span>
      <span class="acts">
        <button class="quiet" data-a="up" title="앞으로" ${i === 0 ? "disabled" : ""}>↑</button>
        <button class="quiet" data-a="down" title="뒤로" ${i === list.length - 1 ? "disabled" : ""}>↓</button>
        <button class="quiet" data-a="del" title="이 장 빼기">✕</button>
      </span>`;
    li.querySelector("img").src = `/media/anim?name=${encodeURIComponent(name)}`;
    li.querySelector(".name").textContent = name.split("/").pop();
    li.addEventListener("click", (e) => {
      const a = e.target.dataset && e.target.dataset.a;
      if (!a) return;
      const next = [...list];
      if (a === "del") next.splice(i, 1);
      else {
        const j = a === "up" ? i - 1 : i + 1;
        [next[i], next[j]] = [next[j], next[i]];
      }
      setAnim(next);
    });
    holder.appendChild(li);
  });
}

async function setAnim(names) {
  try {
    const res = await api("/api/state", { method: "POST", body: JSON.stringify({ ...payload(), anim: names }) });
    state = await res.json();
    fillLook();
    scheduleSync(0);
  } catch (e) {
    toast(e.message);
  }
}

async function addAnim(files) {
  // Images are frames in name order; one GIF replaces whatever was there.
  const list = [...files].sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
  if (!list.length) return;
  toast(`${list.length}개 넣는 중...`);
  try {
    for (const file of list) {
      const res = await api("/api/upload?kind=anim", {
        method: "POST",
        headers: { "X-Name": encodeURIComponent(file.name) },
        body: file,
      });
      state = await res.json();
    }
    fillLook();
    scheduleSync(0);
    toast("넣었습니다. 미리보기에서 끌어 옮기고, 모서리를 끌어 크기를 바꿉니다.", 5000);
  } catch (e) {
    toast(e.message, 6000);
    fillLook();
  }
}

function fillLook() {
  const s = state.style;
  for (const r of document.querySelectorAll('input[name="layout"]')) r.checked = r.value === s.layout;
  for (const r of document.querySelectorAll('input[name="tone"]')) r.checked = r.value === s.tone;
  $("spin").checked = s.spin > 0;
  $("show_cd").checked = s.show_cd;
  $("spin").disabled = !s.show_cd || s.layout !== "case";
  $("show_cd").disabled = s.layout !== "case";
  $("band").value = s.band;
  $("blur").value = s.blur;
  $("dim").value = s.dim;
  $("show_title").checked = s.show_title;
  $("bar").checked = s.bar;
  drawAnim();
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
  $("audio-name").textContent = state.has_audio ? `길이 ${clock(state.duration).replace(/\.\d+$/, "")}` : "없음";
  $("art-name").textContent = state.has_art ? "표지 있음" : "정사각형 권장";
  updateStatus();
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
    if (notes[i]) row.classList.add("doubt");
    row.innerHTML = `
      <span class="n">${i + 1}</span>
      <input class="t" type="text" value="${clockTenth(t)}" placeholder="0:00.0" aria-label="${i + 1}번째 줄 시작">
      <input class="x" type="text" aria-label="${i + 1}번째 줄 가사">
      <span class="nudge">
        <button class="quiet" data-a="minus" title="0.1초 빠르게">−0.1</button>
        <button class="quiet" data-a="plus" title="0.1초 늦게">+0.1</button>
        <button class="quiet" data-a="play" title="이 줄부터 듣기">▶</button>
      </span>
      <button class="quiet" data-a="del" title="이 줄 지우기">✕</button>`;
    row.querySelector(".x").value = text;
    if (notes[i]) {
      const doubt = document.createElement("div");
      doubt.className = "mine";
      doubt.textContent = notes[i];
      row.appendChild(doubt);
    }
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
    const box = row.querySelector(".t");
    const bad = () => box.value.trim() !== "" && parseClock(box.value) == null;
    box.addEventListener("input", () => box.classList.toggle("invalid", bad()));
    box.addEventListener("change", () => {
      if (bad()) {
        box.classList.add("invalid");
        toast("시간 형식: 10, 10.5, 1:05, 1:05.3");
        return;
      }
      state.lines[i][0] = box.value.trim() === "" ? null : parseClock(box.value);
      box.value = clockTenth(state.lines[i][0]);
      updateCheck();
      scheduleSync();
    });
    row.querySelector(".x").addEventListener("change", (e) => { state.lines[i][1] = e.target.value; scheduleSync(); });
    row.addEventListener("click", (e) => {
      const a = e.target.dataset && e.target.dataset.a;
      if (!a) {
        if (!e.target.closest(".mine")) goLine(i);
        return;
      }
      if (a === "minus" || a === "plus") {
        if (state.lines[i][0] == null) return;
        state.lines[i][0] = Math.max(0, Math.round((state.lines[i][0] + (a === "plus" ? 0.1 : -0.1)) * 100) / 100);
        row.querySelector(".t").value = clockTenth(state.lines[i][0]);
        row.querySelector(".t").classList.remove("invalid");
        showAt(state.lines[i][0] + 0.3);
      } else if (a === "play") {
        const p = $("player");
        p.currentTime = Math.max(0, (state.lines[i][0] || 0) - 1);
        p.play();
      } else if (a === "del") {
        const [gone] = state.lines.splice(i, 1);
        const [goneDiff] = diff.splice(i, 1);
        notes = {};
        drawLines();
        scheduleSync();
        toast("줄을 지웠습니다.", 6000, {
          label: "되돌리기",
          run: () => {
            state.lines.splice(i, 0, gone);
            if (diff.length >= i) diff.splice(i, 0, goneDiff);
            drawLines();
            scheduleSync();
          },
        });
      }
    });
    holder.appendChild(row);
  });
  updateCheck();
  markNow(Number($("time").value));
  const next = holder.querySelector(".line.next");
  if (next) next.scrollIntoView({ block: "center", behavior: "smooth" });
}

function updateCheck() {
  const timed = state.lines.filter(([t]) => t != null).length;
  $("check").textContent = state.lines.length ? `시간 입력됨: ${timed} / ${state.lines.length}줄` : "";
  updateStatus();
}

function mark(holder, parts) {
  holder.innerHTML = "";
  for (const [text, cls] of parts) {
    const span = document.createElement("span");
    span.className = cls;
    span.textContent = text;
    holder.append(span);
  }
}

// What each step still lacks, readable from the closed headers before pressing make.
function updateStatus() {
  mark($("state-files"), [
    [state.has_audio ? "노래" : "노래 없음", state.has_audio ? "ok" : "miss"],
    [state.has_art ? "표지" : "표지 없음", state.has_art ? "ok" : "miss"],
  ]);
  const count = state.lines.length;
  mark($("state-lyrics"), [[count ? `${count}줄` : "없음", count ? "" : "miss"]]);
  const timed = state.lines.filter(([t]) => t != null).length;
  mark($("state-timing"), count ? [[`${timed}/${count}`, timed === count ? "ok" : "miss"]] : []);
  $("dot-files").classList.toggle("miss", !(state.has_audio && state.has_art));
  $("dot-lyrics").classList.toggle("miss", !count || timed < count);
}

function lineAt(t) {
  let at = -1;
  state.lines.forEach(([start], i) => {
    if (start != null && start <= t && (at < 0 || start >= state.lines[at][0])) at = i;
  });
  return at;
}

function markNow(t) {
  const at = lineAt(t);
  const rows = $("lines").children;
  for (let i = 0; i < rows.length; i++) rows[i].classList.toggle("now", i === at);
  const row = rows[at];
  if (row && !$("player").paused && !$("lines").contains(document.activeElement)) {
    row.scrollIntoView({ block: "nearest" });
  }
}

function goLine(i) {
  const start = state.lines[i][0];
  if (start == null || tapIndex >= 0) return;
  const p = $("player");
  if (!p.paused) p.currentTime = start;
  showAt(start + 0.3, 0);
}

function showAt(t, delay = 150) {
  $("time").value = t;
  $("time-label").textContent = clock(t).replace(/\.\d+$/, "");
  markNow(t);
  scheduleSync(delay);
}

// While the song plays the still follows it about once a second; a pause or a seek shows that moment.
let follow = null;
function followPlayer() {
  const p = $("player");
  clearInterval(follow);
  follow = null;
  if (!p.paused) {
    follow = setInterval(() => {
      if (!dragging && !document.hidden) showAt(p.currentTime, 0);
    }, 1000);
  }
  showAt(p.currentTime, 0);
}

function togglePlay() {
  const p = $("player");
  if (!state.has_audio) { toast("노래 파일이 없습니다. 왼쪽 파일 묶음에서 넣으세요."); return; }
  if (p.paused) p.play(); else p.pause();
}

function seekBy(seconds) {
  const p = $("player");
  if (!state.has_audio) return;
  p.currentTime = Math.min(Math.max(0, p.currentTime + seconds), p.duration || state.duration || 0);
}

const TEXT_FIELDS = 'input:not([type]), input[type="text"], input[type="number"], textarea, select, [contenteditable]';

// Space and the arrows drive the song unless the key belongs to the focused control: a text field,
// a slider, the audio element, or a button reached with the keyboard.
function shortcut(e) {
  if (e.ctrlKey || e.altKey || e.metaKey || $("crop").open) return;
  const el = document.activeElement;
  if (el && (el.matches(TEXT_FIELDS) || el.tagName === "AUDIO")) return;
  if (e.code === "Space") {
    if (el && el !== document.body && el.matches(":focus-visible")) return;
    if (e.repeat) { e.preventDefault(); return; }
    e.preventDefault();
    if (el && el !== document.body) el.blur();
    togglePlay();
  } else if (e.code === "ArrowLeft" || e.code === "ArrowRight") {
    if (el && el.matches('input[type="range"], input[type="radio"]')) return;
    e.preventDefault();
    seekBy(e.code === "ArrowLeft" ? -5 : 5);
  }
}

const KINDS = {
  audio: [".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac"],
  art: [".png", ".jpg", ".jpeg", ".webp", ".bmp"],
  anim: [".gif", ".png", ".jpg", ".jpeg", ".webp"],
  timing: [".srt", ".lrc", ".vtt"],
  lyrics: [".txt"],
  font: [".ttf", ".otf", ".ttc"],
};

function kindOf(file, onAnim) {
  const name = file.name.toLowerCase();
  const is = (kind) => KINDS[kind].some((s) => name.endsWith(s));
  if (onAnim && is("anim")) return "anim";
  if (name.endsWith(".gif")) return "anim";
  return ["audio", "art", "timing", "lyrics", "font"].find(is) || null;
}

async function takeFiles(files, onAnim) {
  const groups = {};
  for (const file of files) {
    const kind = kindOf(file, onAnim);
    if (!kind) { toast(`${file.name}: 넣을 수 없는 파일입니다. 노래, 사진, 자막, 가사, 글꼴 파일을 놓으세요.`, 6000); continue; }
    (groups[kind] ||= []).push(file);
  }
  if (groups.audio) { await upload("audio", groups.audio[0]); openGroup("files"); }
  if (groups.font) await upload("font", groups.font[0]);
  if (groups.timing) {
    try { await importText(groups.timing[0].name, await groups.timing[0].text()); } catch (e) { toast(e.message); }
    openGroup("lyrics");
  }
  if (groups.lyrics) {
    $("lyrics-text").value = await groups.lyrics[0].text();
    openGroup("lyrics");
    $("lyrics-apply").click();
  }
  if (groups.anim) { await addAnim(groups.anim); openGroup("look"); }
  if (groups.art) openCrop(groups.art[0]);
}

function bindDrop() {
  let depth = 0;
  const hasFiles = (e) => [...(e.dataTransfer?.types || [])].includes("Files");
  document.addEventListener("dragenter", (e) => {
    if (!hasFiles(e)) return;
    depth += 1;
    $("drop").hidden = false;
  });
  document.addEventListener("dragleave", (e) => {
    if (!hasFiles(e)) return;
    depth = Math.max(0, depth - 1);
    if (!depth) $("drop").hidden = true;
  });
  document.addEventListener("dragover", (e) => { if (hasFiles(e)) e.preventDefault(); });
  document.addEventListener("drop", (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    depth = 0;
    $("drop").hidden = true;
    const onAnim = Boolean(e.target.closest && e.target.closest("#anim-group"));
    takeFiles([...e.dataTransfer.files], onAnim).catch((err) => toast(err.message));
  });
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
    toast("완료");
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
  notes = {};
  tapIndex = -1;
  drawLines();
  scheduleSync();
  const bad = diff.filter((d) => d != null).length;
  const sung = data.lines.filter(([, x]) => x).length;
  if (data.own && bad) {
    toast(`${sung}줄을 넣었습니다. 내 가사와 다른 줄 ${bad}개는 테두리로 표시됩니다.`, 6000);
  } else if (data.own && sung !== data.own) {
    toast(`${sung}줄을 넣었습니다. 내 가사(${data.own}줄)와 줄 수가 다르니 목록을 확인하세요.`, 6000);
  } else {
    toast(`${sung}줄을 넣었습니다.`);
  }
}

const PHASES = {
  install: "필요한 프로그램 설치 중 (처음 한 번)",
  download: "듣기 모델 내려받는 중 (처음 한 번)",
  load: "듣기 모델 여는 중",
  listen: "노래 듣는 중",
  align: "가사 맞추는 중",
};

function size(mb) {
  return mb >= 1000 ? `${(mb / 1000).toFixed(1)} GB` : `${Math.round(mb)} MB`;
}

function timeLeft(seconds) {
  if (seconds == null) return "";
  return seconds < 60 ? ` · 남은 시간 약 ${Math.max(1, Math.round(seconds))}초` : ` · 남은 시간 약 ${Math.round(seconds / 60)}분`;
}

async function loadModels() {
  const data = await (await api("/api/auto")).json();
  const m = data.models.small;
  $("auto-size").textContent = m.ready ? "듣기 모델 준비됨." : `첫 사용 시 듣기 모델 ${size(m.size_mb)} 내려받기.`;
  return data;
}

// Times found so far are shown in the list while the song is heard; the list before the run is
// kept so that cancel or an error puts it back.
function showPartial(found) {
  const rows = [];
  pollAuto.before.forEach(([, text], i) => { if (text) rows.push(i); });
  state.lines = pollAuto.before.map(([, text]) => [null, text]);
  for (const [k, t] of found) if (rows[k] != null) state.lines[rows[k]][0] = t;
  drawLines();
}

function restoreLines() {
  if (!pollAuto.before) return;
  state.lines = pollAuto.before;
  pollAuto.before = null;
  drawLines();
}

function showAutoRunning(running) {
  $("auto-progress").hidden = !running;
  $("auto-stop").hidden = !running;
  $("auto-start").disabled = running;
}

async function pollAuto() {
  try {
    const job = await (await api("/api/auto")).json();
    const running = job.state === "running";
    showAutoRunning(running);
    if (running) {
      pollAuto.waiting = true;
      if (!pollAuto.before) pollAuto.before = state.lines.map((row) => [...row]);
      const bar = $("auto-bar");
      const measured = (job.phase === "download" || job.phase === "listen") && job.total > 0;
      const share = measured ? Math.min(1, job.done / job.total) : 0;
      if (measured) bar.value = share; else bar.removeAttribute("value");
      let line = PHASES[job.phase] || "준비 중";
      if (job.phase === "download" && measured) line += ` ${size(job.done)} / ${size(job.total)}`;
      if (job.phase === "listen" && measured) line += ` ${clock(job.done).replace(/\.\d+$/, "")} / ${clock(job.total).replace(/\.\d+$/, "")}`;
      if (measured) line += ` · ${Math.round(share * 100)}%`;
      line += timeLeft(job.eta);
      if (job.phase === "install" && job.detail) line += ` · ${job.detail}`;
      $("auto-text").textContent = line;
      if (job.partial && pollAuto.before) showPartial(job.partial);
      setTimeout(pollAuto, 1000);
      return;
    }
    if (job.state === "done" && pollAuto.waiting) {
      pollAuto.waiting = false;
      pollAuto.before = null;
      state.lines = job.lines;
      diff = [];
      notes = {};
      const lyricIndex = [];
      job.lines.forEach(([, text], i) => { if (text) lyricIndex.push(i); });
      for (const n of job.notes) {
        const at = lyricIndex[n.line];
        notes[at] = n.kind === "unplaced"
          ? "찾지 못한 줄: 앞뒤 줄 사이 시간으로 넣었습니다. 듣고 고치세요."
          : n.kind === "doubtful" ? "앞 줄과 1초 안으로 붙어 있습니다. 듣고 고치세요."
          : `다르게 들림: ${n.heard}`;
      }
      drawLines();
      scheduleSync();
      const sung = lyricIndex.length;
      const bad = job.notes.filter((n) => n.kind !== "differs").length;
      toast(`${sung}줄 중 ${sung - bad}줄의 시간을 찾았습니다.${bad ? ` 확인이 필요한 줄 ${bad}개를 표시했습니다.` : ""}`, 8000);
      loadModels();
    } else if (job.state === "error" && pollAuto.waiting) {
      pollAuto.waiting = false;
      restoreLines();
      toast(`자동 맞추기 실패: ${job.message}`, 10000);
    }
  } catch (e) {
    toast(e.message);
  }
}

function setTab(name) {
  for (const b of document.querySelectorAll(".tab")) {
    b.classList.toggle("active", b.dataset.tab === name);
    b.setAttribute("aria-checked", String(b.dataset.tab === name));
  }
  for (const body of document.querySelectorAll(".tab-body")) body.hidden = body.dataset.body !== name;
  if (name === "auto") loadModels().catch((e) => toast(e.message));
}

function tapNextLabel() {
  if (tapIndex < 0) { $("tap-next").textContent = ""; return; }
  $("tap-next").textContent = tapIndex >= state.lines.length
    ? "모든 줄에 시간이 들어갔습니다. 목록에서 다듬으세요."
    : state.lines[tapIndex][1] || "(빈 줄)";
}

function tap() {
  if (tapIndex < 0 || tapIndex >= state.lines.length) return;
  tapUndo.push([tapIndex, state.lines[tapIndex][0]]);
  state.lines[tapIndex][0] = Math.round($("player").currentTime * 100) / 100;
  tapIndex += 1;
  drawLines();
  tapNextLabel();
  if (tapIndex >= state.lines.length) stopTap(false);
  scheduleSync(600);
}

function untap() {
  const last = tapUndo.pop();
  if (!last) return;
  [tapIndex] = last;
  state.lines[tapIndex][0] = last[1];
  drawLines();
  tapNextLabel();
  scheduleSync(600);
}

function stopTap(pause = true) {
  if (pause) $("player").pause();
  $("tap-bar").hidden = true;
  tapIndex = -1;
  tapUndo = [];
  drawLines();
}

// One group of controls at a time; the timing list under the preview belongs to the lyrics group.
const GROUPS = ["files", "lyrics", "look", "colour"];
const OLD_STEPS = { "step-files": "files", "step-lyrics": "lyrics", "step-timing": "lyrics", "step-look": "look" };

function openGroup(name) {
  for (const g of GROUPS) {
    const on = g === name;
    $(`g-${g}`).hidden = !on;
    $(`tab-${g}`).setAttribute("aria-selected", String(on));
    $(`tab-${g}`).tabIndex = on ? 0 : -1;
  }
  document.querySelector(".steps").scrollTop = 0;
  document.body.classList.toggle("timing-open", name === "lyrics");
}

function bindRail() {
  for (const b of document.querySelectorAll(".rail-tab")) {
    b.addEventListener("click", () => openGroup(b.dataset.group));
    b.addEventListener("keydown", (e) => {
      const step = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 }[e.key];
      if (!step) return;
      e.preventDefault();
      e.stopPropagation();
      const next = GROUPS[(GROUPS.indexOf(b.dataset.group) + step + GROUPS.length) % GROUPS.length];
      openGroup(next);
      $(`tab-${next}`).focus();
    });
  }
}

async function pollRender() {
  let job;
  try {
    job = await (await api("/api/render")).json();
    pollRender.failed = 0;
  } catch (e) {
    // One lost request must not end the watch: the render keeps running in its own process.
    pollRender.failed = (pollRender.failed || 0) + 1;
    if (pollRender.failed === 5) {
      showRenderError("프로그램에 연결할 수 없습니다. 터미널 창이 열려 있는지 확인하세요.");
    }
    setTimeout(pollRender, 2000);
    return;
  }
  if (job.state === "running") {
    $("progress").hidden = false;
    $("done").hidden = true;
    $("make-error").hidden = true;
    $("make").disabled = true;
    const share = job.total ? job.done / job.total : 0;
    $("progress-bar").value = share;
    $("progress-text").textContent = `${Math.round(share * 100)}%${job.eta != null ? timeLeft(job.eta) : " · 남은 시간 계산 중"}`;
    showRenderPlace(job.done || 0, job.total || state.duration || 0);
    setTimeout(pollRender, 1000);
    return;
  }
  $("progress").hidden = true;
  $("make").disabled = false;
  if (job.state === "done") {
    $("done").hidden = false;
    $("done-name").textContent = job.out.split(/[\\/]/).pop();
  } else if (job.state === "error") {
    showRenderError(`영상 만들기 실패: ${job.message}${job.log ? `\n기록 파일: ${job.log}` : ""}`);
  }
}

async function pollClip() {
  let job;
  try {
    job = await (await api("/api/clip")).json();
  } catch (e) {
    setTimeout(pollClip, 1000);
    return;
  }
  const label = $("clip-label");
  if (job.state === "running") {
    $("clip-make").disabled = true;
    label.textContent = `만드는 중 ${Math.round((job.total ? job.done / job.total : 0) * 100)}%`;
    showRenderPlace((job.at || 0) + (job.done || 0), state.duration || 0);
    setTimeout(pollClip, 500);
    return;
  }
  $("clip-make").disabled = false;
  label.textContent = "10초 미리보기";
  if (job.state === "done") {
    const video = $("clip");
    video.src = job.url;
    video.hidden = false;
    $("boxes").hidden = true;
    label.textContent = "미리보기 닫기";
    video.play().catch(() => {});
  } else if (job.state === "error") {
    toast(`미리보기 영상 실패: ${job.message}`, 9000);
  }
}

function closeClip() {
  const video = $("clip");
  video.pause();
  video.removeAttribute("src");
  video.load();
  video.hidden = true;
  $("boxes").hidden = false;
  $("clip-label").textContent = "10초 미리보기";
}

// Progress in song terms: how far into the song the video is made, and the lyric sung there, so the
// pace reads against the song itself.
function showRenderPlace(done, total) {
  const short = (t) => clock(t).replace(/\.\d+$/, "");
  $("progress-song").textContent = `${short(done)} / ${short(total)}`;
  const at = lineAt(done);
  const text = at < 0 ? "" : state.lines[at][1].trim();
  const el = $("progress-line");
  el.textContent = text || (at < 0 ? "전주" : "간주");
  el.classList.toggle("gap", !text);
}

function showRenderError(message) {
  const el = $("make-error");
  el.textContent = message;
  el.hidden = false;
  toast(message.split("\n")[0], 9000);
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
    if (!text.trim()) { toast("가사 칸이 비어 있습니다. 가사를 붙여 넣으세요."); return; }
    if (state.lines.some(([t]) => t != null) && !confirm("목록의 시간이 지워집니다. 새 가사로 바꾸시겠습니까?")) return;
    const res = await api("/api/import", { method: "POST", headers: { "X-Name": "lyrics.txt" }, body: text });
    state.lines = (await res.json()).lines;
    diff = [];
    drawLines();
    scheduleSync();
    $("state-timing").scrollIntoView({ block: "start", behavior: "smooth" });
    toast(`${state.lines.length}줄을 넣었습니다. 아래 타이밍에서 시간을 맞추세요.`);
  });

  for (const b of document.querySelectorAll(".tab")) b.addEventListener("click", () => setTab(b.dataset.tab));
  bindRail();

  $("tap-start").addEventListener("click", () => {
    if (!state.has_audio) { toast("노래 파일이 없습니다. 왼쪽 파일 묶음에서 넣으세요."); return; }
    if (!state.lines.length) { toast("가사가 없습니다. 왼쪽 가사 묶음에서 가사를 넣으세요."); return; }
    tapIndex = 0;
    tapUndo = [];
    diff = [];
    $("tap-bar").hidden = false;
    const p = $("player");
    p.currentTime = 0;
    p.play();
    drawLines();
    tapNextLabel();
    $("tap-now").focus();
  });
  $("tap-now").addEventListener("click", tap);
  $("tap-undo").addEventListener("click", untap);
  $("tap-stop").addEventListener("click", () => stopTap());
  document.addEventListener("keydown", (e) => {
    if ($("tap-bar").hidden) { shortcut(e); return; }
    const typing = ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName);
    if (typing) return;
    if (e.code === "Space" || e.code === "Enter") {
      e.preventDefault();
      tap();
    } else if (e.code === "Backspace") {
      e.preventDefault();
      untap();
    } else if (e.code === "Escape") {
      stopTap();
    }
  });

  $("prompt-copy").addEventListener("click", async () => {
    try {
      await api("/api/state", { method: "POST", body: JSON.stringify(payload()) });
      const data = await (await api("/api/prompt")).json();
      if (!data.lines) { toast("가사가 없습니다. 왼쪽 가사 묶음에서 가사를 넣으세요."); return; }
      $("prompt").value = data.prompt;
      await navigator.clipboard.writeText(data.prompt);
      toast("복사했습니다. 채팅 AI에 노래 파일과 함께 붙여 넣으세요.", 5000);
    } catch (e) {
      $("prompt").hidden = false;
      $("prompt").select();
      toast("Ctrl+C 를 눌러 복사하세요.");
    }
  });
  $("answer-apply").addEventListener("click", async () => {
    const text = $("answer").value;
    if (!text.trim()) { toast("붙여 넣기 칸이 비어 있습니다. 받은 자막을 붙여 넣으세요."); return; }
    try { await importText("answer.srt", text); } catch (e) { toast(e.message); }
  });
  $("timing-file").addEventListener("change", async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    try { await importText(f.name, await f.text()); } catch (err) { toast(err.message); }
    e.target.value = "";
  });

  $("auto-start").addEventListener("click", async () => {
    if (!state.has_audio) { toast("노래 파일이 없습니다. 왼쪽 파일 묶음에서 넣으세요."); return; }
    if (!state.lines.some(([, x]) => x)) { toast("가사가 없습니다. 왼쪽 가사 묶음에서 가사를 넣으세요."); return; }
    if (state.lines.some(([t]) => t != null) && !confirm("목록의 시간이 새로 찾은 시간으로 바뀝니다. 계속하시겠습니까?")) return;
    const model = document.querySelector('input[name="model"]:checked').value;
    try {
      await api("/api/state", { method: "POST", body: JSON.stringify(payload()) });
      await api("/api/auto", { method: "POST", body: JSON.stringify({ model }) });
      pollAuto.before = state.lines.map((row) => [...row]);
      pollAuto.waiting = true;
      pollAuto();
    } catch (e) {
      toast(e.message, 6000);
    }
  });
  $("auto-stop").addEventListener("click", async () => {
    pollAuto.waiting = false;
    await api("/api/auto/stop", { method: "POST" });
    restoreLines();
    showAutoRunning(false);
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
  for (const r of document.querySelectorAll('input[name="tone"]')) {
    r.addEventListener("change", () => { state.style.tone = r.value; scheduleSync(0); });
  }
  $("spin").addEventListener("change", (e) => { state.style.spin = e.target.checked ? 7 : 0; scheduleSync(0); });
  $("show_cd").addEventListener("change", (e) => { state.style.show_cd = e.target.checked; fillLook(); scheduleSync(0); });
  $("font").addEventListener("change", (e) => { state.style.font = e.target.value; scheduleSync(0); });
  $("band").addEventListener("input", (e) => { state.style.band = e.target.value; scheduleSync(); });
  $("band-cover").addEventListener("click", async () => {
    try {
      const { band } = await (await api("/api/band-from-cover")).json();
      state.style.band = band;
      $("band").value = band;
      scheduleSync(0);
    } catch (e) {
      toast(e.message);
    }
  });
  $("blur").addEventListener("input", (e) => { state.style.blur = Number(e.target.value); scheduleSync(); });
  $("dim").addEventListener("input", (e) => { state.style.dim = Number(e.target.value); scheduleSync(); });
  $("show_title").addEventListener("change", (e) => { state.style.show_title = e.target.checked; scheduleSync(0); });
  $("bar").addEventListener("change", (e) => { state.style.bar = e.target.checked; scheduleSync(0); });
  $("anim-file").addEventListener("change", (e) => { addAnim(e.target.files); e.target.value = ""; });
  $("anim_fps").addEventListener("input", (e) => {
    state.style.anim_fps = Number(e.target.value);
    $("anim-fps-label").textContent = e.target.value;
    scheduleSync();
  });
  $("anim_above").addEventListener("change", (e) => { state.style.anim_above = e.target.checked; scheduleSync(0); });
  $("anim-clear").addEventListener("click", () => setAnim([]));
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

  $("time").addEventListener("input", (e) => {
    const t = Number(e.target.value);
    const p = $("player");
    if (!p.paused) p.currentTime = t;
    showAt(t);
  });
  for (const ev of ["play", "pause", "ended"]) $("player").addEventListener(ev, followPlayer);
  $("player").addEventListener("seeked", () => showAt($("player").currentTime, 0));
  bindDrop();
  $("clip-make").addEventListener("click", async () => {
    if (!$("clip").hidden) return closeClip();
    try {
      await api("/api/state", { method: "POST", body: JSON.stringify(payload()) });
      await api(`/api/clip?t=${Number($("time").value)}`, { method: "POST" });
      $("player").pause();
      pollClip();
    } catch (e) {
      toast(e.message, 6000);
    }
  });

  $("make").addEventListener("click", async () => {
    const untimed = state.lines.findIndex(([t]) => t == null);
    if (untimed >= 0) {
      toast(`${untimed + 1}번째 줄에 시간이 없습니다. 타이밍 목록에서 시간을 넣거나 줄을 지우세요.`, 6000);
      openGroup("lyrics");
      return;
    }
    const minutes = Math.max(1, Math.round((state.duration || 60) / 60));
    if (!confirm(`미리보기 모양 그대로 영상을 만드시겠습니까?\n예상 시간: 약 ${minutes}분 이하`)) return;
    try {
      await api("/api/state", { method: "POST", body: JSON.stringify(payload()) });
      await api("/api/render", { method: "POST" });
      pollRender();
    } catch (e) {
      toast(e.message, 6000);
    }
  });
  $("make-stop").addEventListener("click", async () => {
    if (!confirm("영상 만들기를 멈추시겠습니까?")) return;
    await api("/api/render/stop", { method: "POST" });
  });
  $("open-folder").addEventListener("click", () => api("/api/open", { method: "POST" }));

  $("demo").addEventListener("click", async () => {
    if (state.has_audio && !confirm("지금 작업 대신 데모 노래를 불러오시겠습니까?")) return;
    state = await (await api("/api/demo", { method: "POST" })).json();
    diff = [];
    $("lyrics-text").value = state.lines.map(([, x]) => x).join("\n");
    fillAll();
    openGroup("look");
  });
  $("new").addEventListener("click", async () => {
    if (!confirm("지금 작업을 지우고 새로 시작하시겠습니까? 만든 영상은 남습니다.")) return;
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
    if (!confirm("프로그램을 끝내시겠습니까? 작업은 저장되어 있습니다.")) return;
    await api("/api/quit", { method: "POST" });
    document.body.innerHTML = "<p style='padding:40px;font-size:20px'>프로그램을 끝냈습니다. 이 탭을 닫으세요.</p>";
  });
}

async function boot() {
  bind();
  await loadFonts();
  state = await (await api("/api/state")).json();
  $("lyrics-text").value = state.lines.map(([, x]) => x).join("\n");
  fillAll();
  pollRender();
  pollAuto();
  const params = new URLSearchParams(location.search);
  if (params.get("t")) showAt(Number(params.get("t")));
  setTab(document.querySelector(".tab:not(:disabled)").dataset.tab);
  const group = params.get("group") || OLD_STEPS[params.get("step")];
  openGroup(GROUPS.includes(group) ? group : "files");
  if (group) {
    if (params.get("tab")) setTab(params.get("tab"));
    if (params.get("tapping")) $("tap-start").click();
  }
}

boot().catch((e) => toast(e.message));
