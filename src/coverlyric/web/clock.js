"use strict";

// Times typed into the lyric list. Loaded before app.js; tests/test_clock.py runs it under node.

function clock(seconds) {
  if (seconds == null || Number.isNaN(seconds)) return "";
  const s = Math.max(0, seconds);
  const m = Math.floor(s / 60);
  return `${m}:${(s - m * 60).toFixed(2).padStart(5, "0")}`;
}

// m:ss.d, the form a typed time is shown in once the box loses focus.
function clockTenth(seconds) {
  if (seconds == null || Number.isNaN(seconds)) return "";
  const tenths = Math.round(Math.max(0, seconds) * 10);
  const m = Math.floor(tenths / 600);
  const rest = tenths - m * 600;
  return `${m}:${String(Math.floor(rest / 10)).padStart(2, "0")}.${rest % 10}`;
}

// Accepts seconds (10, 10.5, 10,5), m:ss (1:05, 1:05.3) and h:mm:ss (0:01:05); null for anything else.
function parseClock(text) {
  const t = String(text).trim().replace(",", ".");
  const m = t.match(/^(?:(?:(\d+):)?(\d+):)?(\d+(?:\.\d+)?)$/);
  if (!m) return null;
  const [, h, min, sec] = m;
  if (min != null && Number(sec) >= 60) return null;
  if (h != null && Number(min) >= 60) return null;
  return Number(h || 0) * 3600 + Number(min || 0) * 60 + Number(sec);
}

if (typeof module !== "undefined") module.exports = { clock, clockTenth, parseClock };
