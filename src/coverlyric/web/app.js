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
let notes = {}; // lines to check: not found, or within 1 s of the line before
let heard = {}; // lines heard differently, shown only on hover
let checkAt = -1; // the line the 확인할 줄 bar points at
let peaks = null; // loudest sample per slice of the song, for the strip above the line list
const PEAK_SLICES = 4000;
let tapIndex = -1;
let tapUndo = [];
let syncTimer = null;
let syncing = false;
let again = false;
let lastBoxes = {};
let fits = [];  // per line: [size factor, rows] in the video, from the last preview
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
  return { title: state.title, artist: state.artist, lines: state.lines, style: state.style, anim: state.anim, clean_tags: state.clean_tags };
}

function scheduleSync(delay = 150) {
  sumDeco();
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
      fits = JSON.parse(res.headers.get("X-Fit") || "[]");
      markFits();
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
  img.onerror = () => { URL.revokeObjectURL(url); toast("이 그림을 열 수 없습니다. png 또는 jpg 파일을 고릅니다."); };
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

let looks = null; // {name: style keys} from the server, with the cards' stills

// The value each folded 꾸미기 section holds now, shown on its closed header.
function sumDeco() {
  if (!state) return;
  const s = state.style;
  const font = $("font").selectedOptions[0];
  const tone = document.querySelector(`input[name="tone"][value="${s.tone}"]`);
  const moved = ["album", "panel", "title", "bar", "anim"].some((el) => s[`${el}_x`] || s[`${el}_y`] || s[`${el}_scale`] !== 1);
  $("sum-album").textContent = s.layout === "case" ? "CD 케이스" : "둥근 표지";
  $("sum-text").textContent = font ? font.textContent : "";
  $("sum-colour").textContent = tone ? tone.parentElement.textContent.trim() : "";
  $("sum-ends").textContent = [s.fade ? "페이드" : "", s.intro ? `제목 ${s.intro}초` : ""].filter(Boolean).join(" · ") || "없음";
  $("sum-anim").textContent = state.anim && state.anim.length ? `${state.anim.length}장` : "없음";
  $("sum-place").textContent = moved ? "바꿈" : "처음대로";
  if (looks) {
    for (const card of document.querySelectorAll(".look")) {
      const on = Object.entries(looks[card.dataset.look]).every(([k, v]) => s[k] === v);
      card.classList.toggle("on", on);
      card.setAttribute("aria-checked", String(on));
    }
  }
}

async function loadLooks() {
  if (!state || !state.has_art) return;
  try {
    const data = await (await api(`/api/looks?t=${Number($("time").value)}`, { method: "POST", body: JSON.stringify(payload()) })).json();
    looks = data.looks;
    const holder = $("looks");
    holder.innerHTML = "";
    for (const name of Object.keys(looks)) {
      const card = document.createElement("button");
      card.className = "look";
      card.dataset.look = name;
      card.setAttribute("role", "radio");
      card.innerHTML = `<img alt=""><span></span>`;
      card.querySelector("img").src = data.stills[name];
      card.querySelector("span").textContent = name;
      card.addEventListener("click", () => {
        Object.assign(state.style, looks[name]);
        fillLook();
        scheduleSync(0);
      });
      holder.append(card);
    }
    sumDeco();
  } catch (e) { toast(e.message); }
}

function clipLabel(text, busy) {
  $("clip-label").textContent = text;
  $("clip-make").disabled = busy;
  $("deco-clip").firstChild.textContent = text === "10초 미리보기" ? "여기서 10초 재생" : text;
  $("deco-clip").disabled = busy;
}

// An upright video holds part of the song: clip_from to clip_to, a clip_to of 0 being the end.
function clipEnd() {
  const s = state.style;
  return s.clip_to > 0 ? s.clip_to : state.duration || 0;
}

function fillClip() {
  const s = state.style;
  const end = clipEnd();
  const plain = (t) => clock(t).replace(/\.\d+$/, "");
  $("clip-range").textContent = `${plain(s.clip_from)} – ${plain(end)} (${Math.round(end - s.clip_from)}초)`;
  $("loop").checked = s.loop;
  // The preview runs over what the video holds: the part, or the whole song.
  const time = $("time");
  const upright = s.shape !== "wide";
  time.min = upright ? s.clip_from : 0;
  time.max = Math.max(Number(time.min) + 1, upright ? end : state.duration || 60);
  const t = Number(time.value);
  if (t < Number(time.min) || t > Number(time.max)) {
    time.value = time.min;
    $("time-label").textContent = plain(Number(time.min));
  }
  drawClip();
}

function lineStarts() {
  return state.lines.filter(([start, text]) => start != null && text).map(([start]) => start);
}

function firstLine() {
  const starts = lineStarts();
  return starts.length ? Math.min(...starts) : 0;
}

// A dragged end lands on the nearest line start, or the song's end for the end handle, so the part
// starts and stops where a line does.
function nearestStart(t, orEnd) {
  const marks = lineStarts();
  if (orEnd) marks.push(state.duration || 0);
  return marks.length ? marks.reduce((a, b) => (Math.abs(b - t) < Math.abs(a - t) ? b : a)) : t;
}

function setClip(from, to) {
  const s = state.style;
  const duration = state.duration || 0;
  s.clip_from = Math.max(0, Math.min(from, duration));
  const end = Math.min(duration, Math.max(to, s.clip_from + 1));
  s.clip_to = end >= duration ? 0 : end;
  fillClip();
  showAt(s.clip_from, 0);
}

function songLength() {
  return (state && state.duration) || (peaks && peaks.duration) || 0;
}

function drawClip() {
  const c = $("clip-wave");
  const duration = songLength();
  if (!c.clientWidth || !duration) return;
  const ratio = window.devicePixelRatio || 1;
  const w = (c.width = Math.round(c.clientWidth * ratio));
  const h = (c.height = Math.round(c.clientHeight * ratio));
  const g = c.getContext("2d");
  const css = getComputedStyle(document.documentElement);
  const x = (t) => (t / duration) * w;
  if (peaks) {
    g.fillStyle = css.getPropertyValue("--line");
    for (let px = 0; px < w; px++) {
      const top = peaks[Math.floor((px / w) * peaks.length)] || 0;
      g.fillRect(px, h / 2 - (top * h) / 2, 1, Math.max(1, top * h));
    }
  }
  g.fillStyle = css.getPropertyValue("--muted");
  for (const t of lineStarts()) g.fillRect(Math.round(x(t)), h - 6 * ratio, ratio, 6 * ratio);
  const a = x(state.style.clip_from), b = x(clipEnd());
  g.fillStyle = css.getPropertyValue("--accent");
  g.globalAlpha = 0.22;
  g.fillRect(a, 0, b - a, h);
  g.globalAlpha = 1;
  g.fillRect(Math.round(a), 0, 3 * ratio, h);
  g.fillRect(Math.round(b) - 3 * ratio, 0, 3 * ratio, h);
  g.fillStyle = css.getPropertyValue("--ink");
  g.fillRect(Math.round(x(Number($("time").value))), 0, ratio, h);
}

// The handles at the part's two ends are dragged; a press inside the part moves the preview there.
function bindClip() {
  const c = $("clip-wave");
  let held = null;
  const timeAt = (e) => Math.min(songLength(), Math.max(0, (e.offsetX / c.clientWidth) * songLength()));
  const handle = (e) => {
    const px = (t) => (t / songLength()) * c.clientWidth;
    const a = Math.abs(px(state.style.clip_from) - e.offsetX);
    const b = Math.abs(px(clipEnd()) - e.offsetX);
    if (Math.min(a, b) > 8) return null;
    return a < b ? "from" : "to";
  };
  c.addEventListener("pointermove", (e) => {
    if (!songLength()) return;
    if (!held) {
      c.style.cursor = handle(e) ? "ew-resize" : "";
      return;
    }
    const s = state.style;
    const t = nearestStart(timeAt(e), held === "to");
    if (held === "from" && t < clipEnd() - 0.5) s.clip_from = t;
    if (held === "to" && t > s.clip_from + 0.5) s.clip_to = t >= state.duration ? 0 : t;
    fillClip();
  });
  c.addEventListener("pointerdown", (e) => {
    if (!songLength()) return;
    held = handle(e);
    if (held) {
      c.setPointerCapture(e.pointerId);
      return;
    }
    const t = timeAt(e);
    if (t >= state.style.clip_from && t <= clipEnd()) showAt(t, 0);
  });
  const release = () => {
    if (!held) return;
    held = null;
    showAt(state.style.clip_from, 0);
  };
  c.addEventListener("pointerup", release);
  c.addEventListener("pointercancel", release);
  new ResizeObserver(drawClip).observe(c);
}

// Plays the part once from its start and stops at its end; a second press stops it.
function playClip() {
  const p = $("player");
  if (!state.has_audio) { toast("노래 파일이 없습니다. 왼쪽 파일 묶음에서 넣습니다."); return; }
  if (!p.paused) { p.pause(); return; }
  p.currentTime = state.style.clip_from;
  p.play();
  $("clip-play").textContent = "■ 멈추기";
  const watch = () => {
    if (!p.paused && p.currentTime < clipEnd()) { requestAnimationFrame(watch); return; }
    p.pause();
    $("clip-play").textContent = "▶ 구간 듣기";
  };
  requestAnimationFrame(watch);
}

function swatchColour(b) {
  return b.dataset.colour === "band" ? state.style.band : b.dataset.colour;
}

function fillBars() {
  const s = state.style;
  $("bars").checked = s.bars;
  $("bars-options").hidden = !s.bars;
  $("bars_colour").value = s.bars_colour;
  $("bars_height").value = s.bars_height;
  $("bars_top").value = s.bars_top;
  $("bars_bottom").value = s.bars_bottom;
  $("bars_size").value = s.bars_size;
  for (const b of document.querySelectorAll("#bars-swatches button")) {
    b.style.background = swatchColour(b);
    b.setAttribute("aria-pressed", String(swatchColour(b).toLowerCase() === s.bars_colour.toLowerCase()));
  }
}

const RATIOS = { wide: "16 / 9", tall: "9 / 16", square: "1 / 1", portrait: "4 / 5" };

function fillLook() {
  const s = state.style;
  for (const r of document.querySelectorAll('input[name="layout"]')) r.checked = r.value === s.layout;
  for (const r of document.querySelectorAll('input[name="tone"]')) r.checked = r.value === s.tone;
  for (const r of document.querySelectorAll('input[name="shape"]')) r.checked = r.value === s.shape;
  document.body.classList.toggle("upright", s.shape !== "wide");
  document.body.style.setProperty("--ratio", RATIOS[s.shape] || RATIOS.wide);
  fillClip();
  fillBars();
  $("spin").checked = s.spin > 0;
  $("show_cd").checked = s.show_cd;
  $("spin").disabled = !s.show_cd || s.layout !== "case";
  $("tilt").value = s.tilt;
  $("tilt-label").textContent = s.tilt;
  $("show_cd").disabled = s.layout !== "case";
  $("floor").value = s.floor;
  $("reflection").checked = s.reflection;
  $("reflection").disabled = s.layout !== "case";
  $("band").value = s.band;
  $("blur").value = s.blur;
  $("dim").value = s.dim;
  $("vignette").value = s.vignette;
  $("lyric_colour").value = s.lyric_colour;
  $("lyric_edge").value = s.lyric_edge;
  $("lyric_edge_colour").value = s.lyric_edge_colour;
  $("lyric-edge-colour-row").hidden = s.lyric_edge === "none";
  $("show_title").checked = s.show_title;
  $("intro").value = String(s.intro);
  $("bar").checked = s.bar;
  $("fade").checked = s.fade;
  $("height").value = String(s.height);
  $("fps").value = String(s.fps);
  $("lead").value = String(s.lead);
  $("tail").value = String(s.tail);
  drawAnim();
  fillPlaces();
  const select = $("font");
  if (![...select.options].some((o) => o.value === s.font)) {
    const o = new Option(s.font.split(/[\\/]/).pop(), s.font);
    select.add(o);
  }
  select.value = s.font;
  sumDeco();
}

// The folder's last two parts fit the footer; the whole path is in the tooltip.
function showOutput() {
  const parts = (state.output || "").split(/[\\/]/).filter(Boolean);
  $("out-path").textContent = parts.slice(-2).join("\\");
  $("out-path").title = state.output || "";
  $("out-default").hidden = state.output_default !== false;
}

async function chooseOutput(body) {
  try {
    const s = await (await api("/api/output", { method: "POST", body: JSON.stringify(body) })).json();
    state.output = s.output;
    state.output_default = s.output_default;
    showOutput();
  } catch (e) { toast(e.message, 6000); }
}

async function saveTiming(fmt) {
  try {
    const saved = await (await api(`/api/save-timing?fmt=${fmt}`, { method: "POST" })).json();
    toast(`저장했습니다: ${saved.path}`, 8000, { label: "폴더 열기", run: () => api("/api/open", { method: "POST" }) });
  } catch (e) { toast(e.message, 6000); }
}

function fillAll() {
  $("title").value = state.title;
  $("artist").value = state.artist;
  $("clean_tags").checked = state.clean_tags !== false;
  $("audio-name").textContent = state.has_audio ? `길이 ${clock(state.duration).replace(/\.\d+$/, "")}` : "없음";
  $("art-name").textContent = state.has_art ? "표지 있음" : "정사각형 권장";
  updateStatus();
  showOutput();
  if (state.has_audio) $("player").src = `/media/audio?v=${Date.now()}`;
  else $("player").removeAttribute("src");
  loadWave();
  $("time").max = Math.max(1, state.duration || 60);
  fillLook();
  drawLines();
  scheduleSync(0);
}

function drawLines() {
  drawWave();
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
    if (i === checkAt) row.classList.add("checking");
    if (heard[i]) row.title = `들린 글자: ${heard[i]}`;
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
      settle(i, row);
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
        settle(i, row);
        showAt(state.lines[i][0] + 0.3);
      } else if (a === "play") {
        const p = $("player");
        p.currentTime = Math.max(0, (state.lines[i][0] || 0) - 1);
        p.play();
      } else if (a === "del") {
        const [gone] = state.lines.splice(i, 1);
        const [goneDiff] = diff.splice(i, 1);
        notes = {};
        heard = {};
        showCheck();
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
  markFits();
  markNow(Number($("time").value));
  const next = holder.querySelector(".line.next");
  if (next) next.scrollIntoView({ block: "center", behavior: "smooth" });
}

function fitKind(i) {
  const f = fits[i];
  if (!f || !state.lines[i] || !state.lines[i][1]) return "";
  return f[1] > 1 ? "wrap" : f[0] < 1 ? "shrink" : "";
}

// Lines too wide for the lyric panel are drawn smaller, or on two rows; the list says which.
function markFits() {
  $("lines").querySelectorAll(".line").forEach((row, i) => {
    const kind = fitKind(i);
    if (kind) row.dataset.fit = kind; else delete row.dataset.fit;
    const box = row.querySelector(".x");
    if (box) box.title = kind === "wrap" ? "영상에서 두 줄로 나뉩니다." : kind === "shrink" ? "영상에서 글자가 작게 표시됩니다." : "";
  });
  updateCheck();
}

function updateCheck() {
  const timed = state.lines.filter(([t]) => t != null).length;
  const long = state.lines.filter((_, i) => fitKind(i)).length;
  const note = long ? ` · 긴 줄 ${long}개 (영상에서 작게 또는 두 줄로 표시)` : "";
  $("check").textContent = state.lines.length ? `시간 입력됨: ${timed} / ${state.lines.length}줄${note}` : "";
  updateStatus();
}

// A finished step shows a check in place of its number; 꾸미기 and 만들기 have nothing to finish.
function updateStatus() {
  const count = state.lines.length;
  const timed = state.lines.filter(([t]) => t != null).length;
  const done = { files: state.has_audio && state.has_art, lyrics: count > 0, timing: count > 0 && timed === count };
  for (const [key, ok] of Object.entries(done)) {
    const n = $(`n-${key}`);
    n.textContent = ok ? "✓" : String(GROUPS.indexOf(key) + 1);
    n.classList.toggle("done", ok);
  }
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

// Lines automatic timing was unsure of, in order; a line whose time is changed by hand is settled.
function checkLines() {
  return Object.keys(notes).map(Number).sort((a, b) => a - b);
}

function showCheck() {
  const list = checkLines();
  $("check-bar").hidden = !list.length;
  if (!list.length) { checkAt = -1; return; }
  if (!list.includes(checkAt)) checkAt = list[0];
  $("check-count").textContent = `확인할 줄 ${list.length}`;
  $("check-why").textContent = `${checkAt + 1} · ${notes[checkAt]}`;
  $("check-at").textContent = `${list.indexOf(checkAt) + 1}/${list.length}`;
}

function moveCheck(step) {
  const list = checkLines();
  if (!list.length) return;
  const at = list.indexOf(checkAt);
  checkAt = list[(at + step + list.length) % list.length];
  for (const row of document.querySelectorAll(".line.checking")) row.classList.remove("checking");
  const row = $("lines").children[checkAt];
  row.classList.add("checking");
  row.scrollIntoView({ block: "nearest" });
  showCheck();
  drawWave();
  goLine(checkAt);
}

function settle(i, row) {
  if (!notes[i]) return;
  delete notes[i];
  row.classList.remove("doubt", "checking");
  showCheck();
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
  drawWave();
  drawClip();
  scheduleSync(delay);
}

// Decoded at 8 kHz in one channel: a four-minute song takes about 8 MB while it is read, then only
// the slices are kept.
async function loadWave() {
  peaks = null;
  drawWave();
  if (!state.has_audio) return;
  try {
    const data = await (await fetch(`/media/audio?v=${Date.now()}`)).arrayBuffer();
    const song = await new OfflineAudioContext(1, 1, 8000).decodeAudioData(data);
    const samples = song.getChannelData(0);
    const step = Math.max(1, Math.floor(samples.length / PEAK_SLICES));
    peaks = new Float32Array(Math.ceil(samples.length / step));
    for (let k = 0; k < peaks.length; k++) {
      let top = 0;
      for (let j = k * step, end = Math.min(samples.length, j + step); j < end; j++) top = Math.max(top, Math.abs(samples[j]));
      peaks[k] = top;
    }
    peaks.duration = song.duration;
  } catch (e) {
    peaks = null; // a format the browser cannot decode: the list works without the strip
  }
  drawWave();
  drawClip();
}

// On the strip a line's mark can be dragged to a new start; anywhere else a press moves the preview.
// A dragged line stays between its neighbours, so the order of the lines never changes.
function markNear(x, width) {
  let best = -1, gap = 6;
  state.lines.forEach(([t, text], i) => {
    if (t == null || !text) return;
    const d = Math.abs((t / peaks.duration) * width - x);
    if (d <= gap) { best = i; gap = d; }
  });
  return best;
}

function bindWave() {
  const wave = $("wave");
  // A mark only moves once the pointer has gone 3 px, so a plain press never shifts a time by rounding.
  let held = -1, downX = 0, from = null;
  const timeAt = (e) => Math.min(peaks.duration, Math.max(0, (e.offsetX / wave.clientWidth) * peaks.duration));
  wave.addEventListener("pointermove", (e) => {
    if (!peaks) return;
    if (held < 0) {
      wave.style.cursor = markNear(e.offsetX, wave.clientWidth) >= 0 ? "ew-resize" : "";
      return;
    }
    if (from === null && Math.abs(e.offsetX - downX) < 3) return;
    from ??= state.lines[held][0];
    const before = state.lines.slice(0, held).findLast(([t]) => t != null);
    const after = state.lines.slice(held + 1).find(([t]) => t != null);
    const low = before ? before[0] + 0.1 : 0;
    const high = after ? after[0] - 0.1 : peaks.duration;
    const t = Math.round(Math.min(high, Math.max(low, timeAt(e))) * 10) / 10;
    state.lines[held][0] = t;
    $("lines").children[held].querySelector(".t").value = clockTenth(t);
    drawWave();
  });
  wave.addEventListener("pointerdown", (e) => {
    if (!peaks) return;
    held = markNear(e.offsetX, wave.clientWidth);
    if (held >= 0) {
      downX = e.offsetX;
      from = null;
      wave.setPointerCapture(e.pointerId);
      return;
    }
    const t = timeAt(e);
    const p = $("player");
    if (!p.paused) p.currentTime = t;
    showAt(t, 0);
  });
  const release = () => {
    if (held < 0) return;
    const i = held, t = state.lines[i][0];
    held = -1;
    if (from === null || t === from) {
      const p = $("player");
      if (!p.paused) p.currentTime = t;
      showAt(t, 0);
      return;
    }
    settle(i, $("lines").children[i]);
    updateCheck();
    showAt(t + 0.3);
  };
  wave.addEventListener("pointerup", release);
  wave.addEventListener("pointercancel", release);
}

function drawWave() {
  const wave = $("wave");
  wave.hidden = !peaks;
  if (!peaks || !wave.clientWidth) return;
  const ratio = window.devicePixelRatio || 1;
  const w = (wave.width = Math.round(wave.clientWidth * ratio));
  const h = (wave.height = Math.round(wave.clientHeight * ratio));
  const g = wave.getContext("2d");
  const css = getComputedStyle(document.documentElement);
  const x = (t) => (t / peaks.duration) * w;
  g.fillStyle = css.getPropertyValue("--line");
  for (let px = 0; px < w; px++) {
    const top = peaks[Math.floor((px / w) * peaks.length)] || 0;
    g.fillRect(px, h / 2 - (top * h) / 2, 1, Math.max(1, top * h));
  }
  g.font = `${11 * ratio}px sans-serif`;
  state.lines.forEach(([t, text], i) => {
    if (t == null || !text) return;
    g.fillStyle = css.getPropertyValue(i === checkAt ? "--warn" : notes[i] ? "--warn" : "--muted");
    g.globalAlpha = i === checkAt || !notes[i] ? 1 : 0.6;
    g.fillRect(Math.round(x(t)), 0, ratio, h);
    g.fillText(String(i + 1), x(t) + 3 * ratio, 12 * ratio);
  });
  g.globalAlpha = 1;
  g.fillStyle = css.getPropertyValue("--accent");
  g.fillRect(Math.round(x(Number($("time").value))), 0, 2 * ratio, h);
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
  if (!state.has_audio) { toast("노래 파일이 없습니다. 왼쪽 파일 묶음에서 넣습니다."); return; }
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
    if (!kind) { toast(`${file.name}: 넣을 수 없는 파일입니다. 넣을 수 있는 파일: 노래, 사진, 자막, 가사, 글꼴.`, 6000); continue; }
    (groups[kind] ||= []).push(file);
  }
  if (groups.audio) { await upload("audio", groups.audio[0]); openGroup("files"); }
  if (groups.font) await upload("font", groups.font[0]);
  if (groups.timing) {
    try { await importText(groups.timing[0].name, await groups.timing[0].text()); } catch (e) { toast(e.message); }
    openGroup("timing");
  }
  if (groups.lyrics) {
    $("lyrics-text").value = await groups.lyrics[0].text();
    openGroup("lyrics");
    $("lyrics-apply").click();
  }
  if (groups.anim) { await addAnim(groups.anim); openGroup("deco"); }
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
    headers: { "X-Name": encodeURIComponent(name), "X-Clean": state.clean_tags === false ? "0" : "1" },
    body: text,
  });
  const data = await res.json();
  state.lines = data.lines;
  diff = data.diff;
  notes = {};
  heard = {};
  showCheck();
  tapIndex = -1;
  drawLines();
  scheduleSync();
  const bad = diff.filter((d) => d != null).length;
  const sung = data.lines.filter(([, x]) => x).length;
  if (data.own && bad) {
    toast(`${sung}줄을 넣었습니다. 내 가사와 다른 줄 ${bad}개는 테두리로 표시됩니다.`, 6000);
  } else if (data.own && sung !== data.own) {
    toast(`${sung}줄을 넣었습니다. 내 가사(${data.own}줄)와 줄 수가 다르니 목록을 확인합니다.`, 6000);
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
  $("auto-size").textContent = m.ready ? "" : `처음 한 번 듣기 모델 ${size(m.size_mb)} 내려받기`;
  $("auto-size").hidden = m.ready;
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
      if (job.smaller) line += ` · 메모리가 부족해 더 작은 모델(${job.smaller})로 하는 중`;
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
      heard = {};
      const lyricIndex = [];
      job.lines.forEach(([, text], i) => { if (text) lyricIndex.push(i); });
      for (const n of job.notes) {
        const at = lyricIndex[n.line];
        if (n.kind === "differs") heard[at] = n.heard;
        else notes[at] = n.kind === "unplaced" ? "못 찾음, 앞뒤 줄 사이에 둠" : "앞 줄과 1초 안";
      }
      checkAt = -1;
      showCheck();
      drawLines();
      scheduleSync();
      const sung = lyricIndex.length;
      const bad = job.notes.filter((n) => n.kind !== "differs").length;
      const smaller = job.smaller ? ` 메모리가 부족해 더 작은 모델(${job.smaller})로 맞췄으니 시간을 한 번 더 확인합니다.` : "";
      const said = `${sung}줄 중 ${sung - bad}줄의 시간을 찾았습니다.${bad ? ` 확인이 필요한 줄 ${bad}개를 표시했습니다.` : ""}${smaller}`;
      toast(said, 10000);
      $("auto-done-text").textContent = said;
      $("auto-done").hidden = false;
      loadModels();
    } else if (job.state === "error" && pollAuto.waiting) {
      pollAuto.waiting = false;
      restoreLines();
      const instead = job.instead || [];
      $("auto-failed-text").textContent = job.message;
      for (const b of document.querySelectorAll("[data-instead]")) b.hidden = !instead.includes(b.dataset.instead);
      $("auto-failed").hidden = false;
      $("auto-failed").scrollIntoView({ block: "nearest", behavior: "smooth" });
      toast(job.message, 10000);
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
    ? "모든 줄에 시간이 들어갔습니다. 목록에서 다듬습니다."
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

// One step at a time; the line list under the preview belongs to the lyrics and timing steps.
const GROUPS = ["files", "lyrics", "timing", "deco", "make"];
const PANES = { files: ["g-files"], lyrics: ["g-lyrics"], timing: ["g-timing"], deco: ["g-deco"], make: ["g-make"] };
const OLD_GROUPS = { look: "deco", colour: "deco", "step-files": "files", "step-lyrics": "lyrics", "step-timing": "timing", "step-look": "deco" };

function openGroup(name) {
  for (const g of GROUPS) {
    const on = g === name;
    for (const id of PANES[g]) $(id).hidden = !on;
    $(`tab-${g}`).setAttribute("aria-selected", String(on));
    $(`tab-${g}`).tabIndex = on ? 0 : -1;
  }
  document.querySelector(".steps").scrollTop = 0;
  document.body.classList.toggle("timing-open", name === "lyrics" || name === "timing");
  if (name === "deco") loadLooks();
}

function bindRail() {
  for (const b of document.querySelectorAll(".next-step")) b.addEventListener("click", () => openGroup(b.dataset.next));
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
      showRenderError("프로그램에 연결할 수 없습니다. 터미널 창이 열려 있는지 확인합니다.");
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
    showRenderPlace(job.done || 0, job.total || videoLength());
    setTimeout(pollRender, 1000);
    return;
  }
  $("progress").hidden = true;
  $("make").disabled = false;
  if (job.state === "done") {
    $("done").hidden = false;
    $("done-name").textContent = job.out.split(/[\\/]/).pop();
    $("done-name").title = job.out;
    $("done-note").textContent = job.note || "";
    $("done-note").hidden = !job.note;
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
  if (job.state === "running") {
    clipLabel(`만드는 중 ${Math.round((job.total ? job.done / job.total : 0) * 100)}%`, true);
    showRenderPlace((job.at || 0) + (job.done || 0), videoLength());
    setTimeout(pollClip, 500);
    return;
  }
  clipLabel("10초 미리보기", false);
  if (job.state === "done") {
    const video = $("clip");
    video.src = job.url;
    video.hidden = false;
    $("boxes").hidden = true;
    clipLabel("미리보기 닫기", false);
    video.play().catch(() => {});
    if (job.note) toast(job.note, 9000);
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

// The video is the song with the silence before and after it.
function videoLength() {
  return (state.duration || 0) + (state.style.lead || 0) + (state.style.tail || 0);
}

// Progress on the video's clock, and the lyric sung there, so the pace reads against the song itself.
function showRenderPlace(done, total) {
  const short = (t) => clock(t).replace(/\.\d+$/, "");
  $("progress-song").textContent = `${short(done)} / ${short(total)}`;
  const at = lineAt(done - (state.style.lead || 0));
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
  $("clean_tags").addEventListener("change", (e) => { state.clean_tags = e.target.checked; scheduleSync(0); });

  $("lyrics-apply").addEventListener("click", async () => {
    const text = $("lyrics-text").value;
    if (!text.trim()) { toast("가사 칸이 비어 있습니다. 가사를 붙여 넣습니다."); return; }
    if (state.lines.some(([t]) => t != null) && !confirm("목록의 시간이 지워집니다. 새 가사로 바꾸시겠습니까?")) return;
    const res = await api("/api/import", { method: "POST", headers: { "X-Name": "lyrics.txt", "X-Clean": state.clean_tags === false ? "0" : "1" }, body: text });
    state.lines = (await res.json()).lines;
    diff = [];
    drawLines();
    scheduleSync();
    openGroup("timing");
    toast(`${state.lines.length}줄을 넣었습니다.`);
  });

  for (const b of document.querySelectorAll(".tab")) b.addEventListener("click", () => setTab(b.dataset.tab));
  bindRail();
  new ResizeObserver(() => drawWave()).observe($("wave"));
  bindWave();
  $("check-prev").addEventListener("click", () => moveCheck(-1));
  $("deco-clip").addEventListener("click", () => $("clip-make").click());
  $("check-next").addEventListener("click", () => moveCheck(1));

  $("tap-start").addEventListener("click", () => {
    if (!state.has_audio) { toast("노래 파일이 없습니다. 왼쪽 파일 묶음에서 넣습니다."); return; }
    if (!state.lines.length) { toast("가사가 없습니다. 왼쪽 가사 묶음에서 가사를 넣습니다."); return; }
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
      if (!data.lines) { toast("가사가 없습니다. 왼쪽 가사 묶음에서 가사를 넣습니다."); return; }
      $("prompt").value = data.prompt;
      await navigator.clipboard.writeText(data.prompt);
      toast("복사했습니다. 채팅 AI에 노래 파일과 함께 붙여 넣습니다.", 5000);
    } catch (e) {
      $("prompt").hidden = false;
      $("prompt").select();
      toast("Ctrl+C 를 눌러 복사합니다.");
    }
  });
  $("answer-apply").addEventListener("click", async () => {
    const text = $("answer").value;
    if (!text.trim()) { toast("붙여 넣기 칸이 비어 있습니다. 받은 자막을 붙여 넣습니다."); return; }
    try { await importText("answer.srt", text); } catch (e) { toast(e.message); }
  });
  $("timing-file").addEventListener("change", async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    try { await importText(f.name, await f.text()); } catch (err) { toast(err.message); }
    e.target.value = "";
  });

  $("auto-start").addEventListener("click", async () => {
    if (!state.has_audio) { toast("노래 파일이 없습니다. 왼쪽 파일 묶음에서 넣습니다."); return; }
    if (!state.lines.some(([, x]) => x)) { toast("가사가 없습니다. 왼쪽 가사 묶음에서 가사를 넣습니다."); return; }
    if (state.lines.some(([t]) => t != null) && !confirm("목록의 시간이 새로 찾은 시간으로 바뀝니다. 계속하시겠습니까?")) return;
    const model = document.querySelector('input[name="model"]:checked').value;
    try {
      await api("/api/state", { method: "POST", body: JSON.stringify(payload()) });
      await api("/api/auto", { method: "POST", body: JSON.stringify({ model }) });
      $("auto-failed").hidden = true;
      $("auto-done").hidden = true;
      pollAuto.before = state.lines.map((row) => [...row]);
      pollAuto.waiting = true;
      pollAuto();
    } catch (e) {
      toast(e.message, 6000);
    }
  });
  for (const b of document.querySelectorAll("[data-instead]")) {
    b.addEventListener("click", () => {
      setTab(b.dataset.instead);
      document.querySelector(`.tab[data-tab="${b.dataset.instead}"]`).scrollIntoView({ block: "nearest", behavior: "smooth" });
    });
  }
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
  $("clip-play").addEventListener("click", playClip);
  $("clip-chorus").addEventListener("click", async () => {
    const length = Math.round(clipEnd() - state.style.clip_from) || 30;
    try {
      const res = await api(`/api/chorus?len=${length}`, { method: "POST", body: JSON.stringify(payload()) });
      const found = await res.json();
      if (found.from == null) toast("두 번 이상 나오는 줄이 없어 후렴을 찾지 못했습니다.");
      else setClip(found.from, found.to);
    } catch (e) {
      toast(e.message);
    }
  });
  bindClip();
  $("bars").addEventListener("change", (e) => { state.style.bars = e.target.checked; fillBars(); scheduleSync(0); });
  for (const b of document.querySelectorAll("#bars-swatches button")) {
    b.addEventListener("click", () => { state.style.bars_colour = swatchColour(b); fillBars(); scheduleSync(0); });
  }
  $("bars_colour").addEventListener("input", (e) => { state.style.bars_colour = e.target.value; fillBars(); scheduleSync(); });
  for (const key of ["bars_height", "bars_size"]) {
    $(key).addEventListener("input", (e) => { state.style[key] = Number(e.target.value); scheduleSync(); });
  }
  for (const key of ["bars_top", "bars_bottom"]) {
    $(key).addEventListener("input", (e) => { state.style[key] = e.target.value; scheduleSync(); });
  }
  $("loop").addEventListener("change", (e) => { state.style.loop = e.target.checked; scheduleSync(0); });
  // Leaving 16:9 sets what a phone video needs (the server's tall.SHORTS); 16:9 goes back to 24 fps.
  for (const r of document.querySelectorAll('input[name="shape"]')) {
    r.addEventListener("change", () => {
      const s = state.style;
      const upright = r.value !== "wide";
      if (upright && s.shape === "wide") Object.assign(s, state.shorts);
      if (!upright) s.fps = 24;
      s.shape = r.value;
      fillLook();
      // It starts on the hook: with no part chosen yet, 30 s from the first sung line.
      if (upright && !s.clip_from && !s.clip_to) setClip(firstLine(), firstLine() + 30);
      scheduleSync(0);
    });
  }
  $("spin").addEventListener("change", (e) => { state.style.spin = e.target.checked ? 7 : 0; scheduleSync(0); });
  $("tilt").addEventListener("input", (e) => {
    state.style.tilt = Number(e.target.value);
    $("tilt-label").textContent = e.target.value;
    scheduleSync();
  });
  $("floor").addEventListener("input", (e) => { state.style.floor = Number(e.target.value); scheduleSync(); });
  $("reflection").addEventListener("change", (e) => { state.style.reflection = e.target.checked; scheduleSync(0); });
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
  $("vignette").addEventListener("input", (e) => { state.style.vignette = Number(e.target.value); scheduleSync(); });
  $("lyric_colour").addEventListener("input", (e) => { state.style.lyric_colour = e.target.value; scheduleSync(); });
  $("lyric_edge").addEventListener("change", (e) => {
    state.style.lyric_edge = e.target.value;
    $("lyric-edge-colour-row").hidden = e.target.value === "none";
    scheduleSync(0);
  });
  $("lyric_edge_colour").addEventListener("input", (e) => { state.style.lyric_edge_colour = e.target.value; scheduleSync(); });
  $("show_title").addEventListener("change", (e) => { state.style.show_title = e.target.checked; scheduleSync(0); });
  $("intro").addEventListener("change", (e) => { state.style.intro = Number(e.target.value); scheduleSync(0); });
  $("bar").addEventListener("change", (e) => { state.style.bar = e.target.checked; scheduleSync(0); });
  $("fade").addEventListener("change", (e) => { state.style.fade = e.target.checked; scheduleSync(0); });
  $("height").addEventListener("change", (e) => { state.style.height = Number(e.target.value); scheduleSync(0); });
  $("fps").addEventListener("change", (e) => { state.style.fps = Number(e.target.value); scheduleSync(0); });
  for (const key of ["lead", "tail"]) {
    $(key).addEventListener("change", (e) => {
      const seconds = Math.min(10, Math.max(0, Math.round((Number(e.target.value) || 0) * 2) / 2));
      e.target.value = String(seconds);
      state.style[key] = seconds;
      scheduleSync(0);
    });
  }
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
      toast(`${untimed + 1}번째 줄에 시간이 없습니다. 타이밍 목록에서 시간을 넣거나 줄을 지웁니다.`, 6000);
      openGroup("timing");
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
  $("done-play").addEventListener("click", () => api("/api/open-video", { method: "POST" }));
  $("out-open").addEventListener("click", () => api("/api/open", { method: "POST" }));
  $("out-pick").addEventListener("click", () => chooseOutput({}));
  $("out-default").addEventListener("click", () => chooseOutput({ folder: "" }));
  for (const id of ["save-lrc", "save-srt"]) $(id).addEventListener("click", (e) => saveTiming(e.currentTarget.dataset.fmt));
  $("auto-save-srt").addEventListener("click", () => saveTiming("srt"));

  $("demo").addEventListener("click", async () => {
    if (state.has_audio && !confirm("지금 작업 대신 데모 노래를 불러오시겠습니까?")) return;
    state = await (await api("/api/demo", { method: "POST" })).json();
    diff = [];
    $("lyrics-text").value = state.lines.map(([, x]) => x).join("\n");
    fillAll();
    openGroup("deco");
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
    document.body.innerHTML = "<p style='padding:40px;font-size:20px'>프로그램을 끝냈습니다. 이 탭은 닫아도 됩니다.</p>";
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
  const asked = params.get("group") || params.get("step");
  const group = OLD_GROUPS[asked] || asked;
  openGroup(GROUPS.includes(group) ? group : "files");
  if (group) {
    if (params.get("tab")) setTab(params.get("tab"));
    if (params.get("tapping")) $("tap-start").click();
  }
}

boot().catch((e) => toast(e.message));
