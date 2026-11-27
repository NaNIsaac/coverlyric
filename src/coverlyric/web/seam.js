"use strict";

// One pass of a looping Short's sound, as the render joins it: the part from `from` to `to` seconds,
// its last `blend` seconds crossing at equal power (the render's qsin fades) into the sound just
// before `from`, so played on repeat the end runs into the start. `channels` are the song's samples
// per channel at `rate`. A blend under MIN_BLEND (tall.MIN_BLEND) is a plain jump, and a part
// starting earlier than the blend blends over what there is, as in tall.loop_length. Loaded before
// app.js; tests/test_seam.py runs it under node.

const MIN_BLEND = 0.05;

function seamLoop(channels, rate, from, to, blend) {
  const a = Math.max(0, Math.round(from * rate));
  const b = Math.min(channels[0].length, Math.round(to * rate));
  let n = Math.max(0, Math.min(Math.round(blend * rate), a, b - a));
  if (n < MIN_BLEND * rate) n = 0;
  return channels.map((src) => {
    const out = new Float32Array(b - a);
    out.set(src.subarray(a, b));
    for (let i = 0; i < n; i++) {
      const th = (i / n) * (Math.PI / 2);
      const k = b - a - n + i;
      out[k] = src[a + k] * Math.cos(th) + src[a - n + i] * Math.sin(th);
    }
    return out;
  });
}

if (typeof module !== "undefined") module.exports = { seamLoop };
