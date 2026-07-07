/**
 * Tiny synthesized sound kit — no audio assets, everything is WebAudio.
 * Off by default; the user opts in via the SOUND toggle and the choice
 * persists in localStorage. Every call is a no-op while disabled.
 */
let ctx = null;
let enabled = false;
const LS = "receipt-sound";

export function initSound() {
  enabled = typeof localStorage !== "undefined" && localStorage.getItem(LS) === "1";
  return enabled;
}
export function soundEnabled() {
  return enabled;
}
export function setSound(v) {
  enabled = !!v;
  try { localStorage.setItem(LS, enabled ? "1" : "0"); } catch { /* private mode */ }
  if (enabled) tick(0.9); /* confirm with a soft dot-matrix tick */
}

function ensure() {
  try {
    if (!ctx) ctx = new (window.AudioContext || window.webkitAudioContext)();
    if (ctx.state === "suspended") ctx.resume();
    return ctx;
  } catch {
    return null;
  }
}

function noiseBuf(c, dur) {
  const n = Math.max(1, (dur * c.sampleRate) | 0);
  const b = c.createBuffer(1, n, c.sampleRate);
  const d = b.getChannelData(0);
  for (let i = 0; i < n; i++) d[i] = Math.random() * 2 - 1;
  return b;
}

/** one dot-matrix pin strike — short bandpassed noise burst */
export function tick(vol = 0.5) {
  if (!enabled) return;
  const c = ensure();
  if (!c) return;
  const t = c.currentTime;
  const src = c.createBufferSource();
  src.buffer = noiseBuf(c, 0.02);
  const bp = c.createBiquadFilter();
  bp.type = "bandpass";
  bp.frequency.value = 2600;
  bp.Q.value = 1.4;
  const g = c.createGain();
  g.gain.setValueAtTime(0.05 * vol, t);
  g.gain.exponentialRampToValueAtTime(0.0001, t + 0.03);
  src.connect(bp); bp.connect(g); g.connect(c.destination);
  src.start(t); src.stop(t + 0.04);
}

/** the rubber-stamp slam — low thump + muffled snap */
export function kachunk() {
  if (!enabled) return;
  const c = ensure();
  if (!c) return;
  const t = c.currentTime;
  const o = c.createOscillator();
  o.type = "sine";
  o.frequency.setValueAtTime(150, t);
  o.frequency.exponentialRampToValueAtTime(55, t + 0.13);
  const og = c.createGain();
  og.gain.setValueAtTime(0.22, t);
  og.gain.exponentialRampToValueAtTime(0.0001, t + 0.16);
  o.connect(og); og.connect(c.destination);
  o.start(t); o.stop(t + 0.18);

  const s = c.createBufferSource();
  s.buffer = noiseBuf(c, 0.05);
  const lp = c.createBiquadFilter();
  lp.type = "lowpass";
  lp.frequency.value = 1800;
  const sg = c.createGain();
  sg.gain.setValueAtTime(0.12, t + 0.005);
  sg.gain.exponentialRampToValueAtTime(0.0001, t + 0.07);
  s.connect(lp); lp.connect(sg); sg.connect(c.destination);
  s.start(t + 0.005); s.stop(t + 0.08);
}
