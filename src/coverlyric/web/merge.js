"use strict";

// project.json changed elsewhere (a command, a tool, a second window) while the page held changes of
// its own. Loaded before app.js; tests/test_merge.py runs it under node.

const MERGE_FIELDS = { title: "제목", artist: "가수", album: "앨범", released: "날짜", clean_tags: "태그 정리" };

function sameValue(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

// What the server held: the fields the page edits and merges.
function mergeBase(s) {
  const kept = { current: s.current, lines: s.lines, style: s.style };
  for (const k of Object.keys(MERGE_FIELDS)) kept[k] = s[k];
  return JSON.parse(JSON.stringify(kept));
}

// The file's state (fresh) with the page's own changes (mine against base) put back. A field both
// sides changed keeps the file's value and is listed in `both`, with keep() to take the page's.
function mergeState(base, mine, fresh) {
  const out = JSON.parse(JSON.stringify(fresh));
  const both = [];
  if (!base || base.current !== mine.current || fresh.current !== mine.current) return { out, both };
  const take = (name, m, f, was, keep) => {
    if (sameValue(m, was)) return;
    if (sameValue(f, was) || sameValue(f, m)) keep();
    else both.push({ name, keep });
  };
  for (const [k, name] of Object.entries(MERGE_FIELDS)) take(name, mine[k], fresh[k], base[k], () => { out[k] = mine[k]; });
  for (const k of Object.keys(mine.style || {})) {
    take(`모양 ${k}`, mine.style[k], fresh.style?.[k], base.style?.[k], () => { out.style[k] = mine.style[k]; });
  }
  if (mine.lines.length === base.lines.length && fresh.lines.length === base.lines.length) {
    mine.lines.forEach((line, i) => take(`가사 ${i + 1}줄`, line, fresh.lines[i], base.lines[i], () => { out.lines[i] = line; }));
  } else {
    take("가사", mine.lines, fresh.lines, base.lines, () => { out.lines = mine.lines; });
  }
  return { out, both };
}

if (typeof module !== "undefined") module.exports = { mergeBase, mergeState, sameValue };
