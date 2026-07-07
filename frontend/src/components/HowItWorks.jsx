import { useLayoutEffect, useRef, useState } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import PrintReveal from "./PrintReveal.jsx";

gsap.registerPlugin(ScrollTrigger);

/**
 * HOW IT WORKS — "follow one sale".
 * An SVG storyboard: a receipt chit physically travels a conveyor through the
 * four stations (SELL → SIGN → REGISTER → VERIFY). Desktop pins the section
 * and scrubs the journey with scroll; mobile autoplays it on a swipeable
 * strip. The four step cards double as a progress rail and light up in sync.
 */

const steps = [
  { n: "01", t: "Sell", d: "Ring up the sale on the web POS — phone, tablet or desktop. Amharic-friendly, keyboard-fast, cashier-simple." },
  { n: "02", t: "Sign", d: "Each invoice is canonically serialized and signed SHA512-RSA with an INSA-issued digital certificate. Keys never leave the server." },
  { n: "03", t: "Register", d: "Sent to MoR EIMS in real time. Sequence-chained per business — no invoice can be skipped, duplicated or forged." },
  { n: "04", t: "Verify", d: "MoR returns the IRN and a government-signed QR. Print thermal or A4; anyone can scan and verify the sale instantly." },
];

/* fixed pseudo-QR pattern (5×5) so the modules are stable between renders */
const QR_ON = [1,1,1,0,1, 1,0,1,1,0, 1,1,0,1,1, 0,1,1,0,1, 1,0,1,1,1];

/* chit x waypoints (its left edge) at each station */
const CHIT_X = [118, 400, 672, 918];
const LABELS = [
  { x: 149, text: "01 · SELL" },
  { x: 431, text: "02 · SIGN" },
  { x: 715, text: "03 · REGISTER" },
  { x: 949, text: "04 · VERIFY" },
];

function buildTimeline(q) {
  const tl = gsap.timeline({ defaults: { ease: "power2.inOut" } });

  /* gsap owns the chit's transform outright (an SVG translate attribute would
     be replaced, not composed) — so position it explicitly from frame 0 */
  tl.set(q(".hf-chit"), { x: CHIT_X[0], y: 160 }, 0);

  /* march the conveyor dashes for the entire journey */
  tl.to(q(".hf-conveyor"), { strokeDashoffset: -260, duration: 16, ease: "none" }, 0);

  /* ---- scene 1 · SELL (0 → 2.2) ---- */
  tl.to(q(".hf-screenclip"), { attr: { width: 106 }, duration: 1.1, ease: "none" }, 0.15)
    .fromTo(q(".hf-key-enter"), { fill: "#1c2420" }, { fill: "var(--green)", duration: 0.18, yoyo: true, repeat: 1 }, 1.35)
    .fromTo(q(".hf-chit"), { autoAlpha: 0, y: 134 }, { autoAlpha: 1, y: 160, duration: 0.65, ease: "back.out(1.4)" }, 1.55);

  /* ---- travel 1 (2.2 → 3.6) ---- */
  tl.to(q(".hf-chit"), { x: CHIT_X[1], duration: 1.4, ease: "power1.inOut" }, 2.2)
    .to(q(".hf-chit"), { rotation: 1.6, transformOrigin: "50% 100%", duration: 0.7, yoyo: true, repeat: 1, ease: "sine.inOut" }, 2.2);

  /* ---- scene 2 · SIGN (3.6 → 6.2) ---- */
  tl.to(q(".hf-pen"), { y: 26, rotation: -12, transformOrigin: "50% 0%", duration: 0.5, ease: "power2.in" }, 3.7)
    .to(q(".hf-sig"), { strokeDashoffset: 0, duration: 1.2, ease: "power1.inOut" }, 4.2)
    .to(q(".hf-pen"), { y: 0, rotation: 0, duration: 0.5, ease: "power2.out" }, 5.4)
    .to(q(".hf-seal"), { strokeDashoffset: 0, duration: 1.1, ease: "power1.inOut" }, 4.3)
    .fromTo(q(".hf-seal-txt"), { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.4 }, 5.3)
    .fromTo(q(".hf-sealed"), { autoAlpha: 0, scale: 1.7, transformOrigin: "50% 50%" },
            { autoAlpha: 1, scale: 1, duration: 0.45, ease: "back.out(2.2)" }, 5.6);

  /* ---- travel 2 (6.2 → 7.4) ---- */
  tl.to(q(".hf-chit"), { x: CHIT_X[2], duration: 1.2, ease: "power1.inOut" }, 6.2)
    .to(q(".hf-chit"), { rotation: -1.4, duration: 0.6, yoyo: true, repeat: 1, ease: "sine.inOut" }, 6.2);

  /* ---- scene 3 · REGISTER (7.4 → 10.6) ---- */
  tl.fromTo(q(".hf-pulse-up"), { autoAlpha: 0, attr: { cy: 240 } },
            { autoAlpha: 1, attr: { cy: 152 }, duration: 0.8, ease: "power1.in" }, 7.5)
    .to(q(".hf-pulse-up"), { autoAlpha: 0, duration: 0.15 }, 8.3)
    .to(q(".hf-win"), { fill: "var(--amber)", duration: 0.16, yoyo: true, repeat: 3, stagger: 0.08 }, 8.35)
    .to(q(".hf-win"), { fill: "var(--green)", duration: 0.3, stagger: 0.08 }, 9.15)
    .fromTo(q(".hf-pulse-dn"), { autoAlpha: 0, attr: { cy: 152 } },
            { autoAlpha: 1, attr: { cy: 240 }, duration: 0.7, ease: "power1.in" }, 9.3)
    .to(q(".hf-pulse-dn"), { autoAlpha: 0, duration: 0.15 }, 10.0)
    .to(q(".hf-ctr-old"), { autoAlpha: 0, y: -8, duration: 0.35 }, 9.5)
    .fromTo(q(".hf-ctr-new"), { autoAlpha: 0, y: 8 }, { autoAlpha: 1, y: 0, duration: 0.35 }, 9.6)
    .fromTo(q(".hf-irn"), { autoAlpha: 0, scale: 0, transformOrigin: "50% 50%" },
            { autoAlpha: 1, scale: 1, duration: 0.45, ease: "back.out(2.4)" }, 10.05);

  /* ---- travel 3 (10.6 → 11.8) ---- */
  tl.to(q(".hf-chit"), { x: CHIT_X[3], duration: 1.2, ease: "power1.inOut" }, 10.6)
    .to(q(".hf-chit"), { rotation: 1.4, duration: 0.6, yoyo: true, repeat: 1, ease: "sine.inOut" }, 10.6);

  /* ---- scene 4 · VERIFY (11.8 → 16) ---- */
  tl.fromTo(q(".hf-qr rect"), { scale: 0, transformOrigin: "50% 50%" },
            { scale: 1, duration: 0.3, stagger: { each: 0.028, from: "start" }, ease: "back.out(2)" }, 11.9)
    .fromTo(q(".hf-phone"), { autoAlpha: 0, x: 34 }, { autoAlpha: 1, x: 0, duration: 0.6, ease: "power2.out" }, 12.1)
    .fromTo(q(".hf-beam"), { autoAlpha: 0 }, { autoAlpha: 0.85, duration: 0.3 }, 12.9)
    .to(q(".hf-beam"), { strokeDashoffset: -40, duration: 1.1, ease: "none" }, 12.9)
    .to(q(".hf-beam"), { autoAlpha: 0, duration: 0.3 }, 14.0)
    .fromTo(q(".hf-stamp"), { autoAlpha: 0, scale: 2.4, rotation: -24, transformOrigin: "50% 50%" },
            { autoAlpha: 1, scale: 1, rotation: -9, duration: 0.7, ease: "back.out(1.9)" }, 14.2)
    .fromTo(q(".hf-phone-ok"), { autoAlpha: 0, scale: 0, transformOrigin: "50% 50%" },
            { autoAlpha: 1, scale: 1, duration: 0.4, ease: "back.out(2.6)" }, 14.9)
    .to({}, { duration: 0.8 }, 15.2); /* hold the finished frame */

  return tl;
}

/* timeline seconds → active card index */
const stepAt = (t) => (t < 2.9 ? 0 : t < 6.8 ? 1 : t < 11.2 ? 2 : 3);

export default function HowItWorks() {
  const root = useRef(null);
  const [active, setActive] = useState(-1);

  useLayoutEffect(() => {
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const ctx = gsap.context((self) => {
      const q = (sel) => self.selector(sel);

      if (reduced) { buildTimeline(q).progress(1).pause(); setActive(3); return; }

      const mm = gsap.matchMedia();

      /* Desktop: pin the section, scroll drives the journey. */
      mm.add("(min-width: 881px)", () => {
        const tl = buildTimeline(q);
        tl.eventCallback("onUpdate", () => setActive(stepAt(tl.time())));
        ScrollTrigger.create({
          animation: tl,
          trigger: root.current,
          start: "top top",
          end: "+=160%",
          scrub: 0.4,
          pin: true,
          anticipatePin: 1,
          invalidateOnRefresh: true,
        });
        return () => setActive(-1);
      });

      /* Mobile: swipeable strip; the journey autoplays in a loop once seen,
         and the strip gently pans to keep the chit in frame. */
      mm.add("(max-width: 880px)", () => {
        const wrap = root.current.querySelector(".howflow-wrap");
        const tl = buildTimeline(q);
        tl.repeat(-1).repeatDelay(1.6).pause();
        tl.eventCallback("onUpdate", () => {
          setActive(stepAt(tl.time()));
          if (wrap) {
            const max = wrap.scrollWidth - wrap.clientWidth;
            /* hold on station 1 until the chit departs (t≈2.2), then follow it */
            const p = Math.min(1, Math.max(0, (tl.time() - 2.2) / 10.5));
            if (max > 0) wrap.scrollLeft = max * p;
          }
        });
        ScrollTrigger.create({
          trigger: root.current,
          start: "top 75%",
          end: "bottom top",
          onToggle: (t) => (t.isActive ? tl.play() : tl.pause()),
        });
        return () => setActive(-1);
      });
    }, root);
    return () => ctx.revert();
  }, []);

  const label = { fontFamily: "IBM Plex Mono, monospace", fontSize: 11, letterSpacing: ".18em" };
  const chitLine = (x1, y, x2, w = 1.6) => (
    <line x1={x1} y1={y} x2={x2} y2={y} stroke="#c4bfae" strokeWidth={w} />
  );

  return (
    <section ref={root} id="how" className="section"
             style={{ background: "var(--bg-2)", overflow: "hidden", padding: "clamp(48px,6vw,84px) 0 44px" }}>
      <div className="container">
        <div className="kicker">HOW IT WORKS <span className="dots" /> FOLLOW ONE SALE</div>
        <PrintReveal className="h2">From “thank you”<br />to <em>tax-office truth.</em></PrintReveal>

        {/* ---------- SVG storyboard ---------- */}
        <div className="howflow-wrap">
          <svg className="howflow" viewBox="0 0 1060 300" fill="none" role="img"
               aria-label="A receipt travels from the POS, gets digitally signed, is registered at the Ministry of Revenue and comes back with a verified QR code.">

            {/* conveyor */}
            <line className="hf-conveyor" x1="40" y1="246" x2="1020" y2="246"
                  stroke="var(--line)" strokeWidth="2" strokeDasharray="7 6" />
            {[0, 1, 2, 3].map((i) => (
              <text key={i} x={LABELS[i].x} y="284" textAnchor="middle" style={label}
                    fill={active === i ? "var(--green)" : "var(--muted)"}>
                {LABELS[i].text}
              </text>
            ))}

            {/* ---- station 1 · POS terminal ---- */}
            <g>
              <rect x="64" y="92" width="134" height="100" rx="9" fill="var(--bezel)" />
              <rect x="76" y="104" width="110" height="48" rx="4" fill="#1c2420" />
              <clipPath id="hfScreenClip"><rect className="hf-screenclip" x="78" y="104" width="0" height="48" /></clipPath>
              <g clipPath="url(#hfScreenClip)" fontFamily="IBM Plex Mono, monospace">
                <text x="83" y="123" fontSize="9" fill="#cfe8d8">MACCHIATO</text>
                <text x="179" y="123" fontSize="9" fill="#cfe8d8" textAnchor="end">100.00</text>
                <text x="83" y="141" fontSize="9" fill="#39d98a" fontWeight="600">TOTAL</text>
                <text x="179" y="141" fontSize="9" fill="#39d98a" textAnchor="end" fontWeight="600">ETB 100.00</text>
              </g>
              <rect x="76" y="162" width="24" height="16" rx="3" fill="#1c2420" />
              <rect x="106" y="162" width="24" height="16" rx="3" fill="#1c2420" />
              <rect className="hf-key-enter" x="136" y="162" width="50" height="16" rx="3" fill="#1c2420" />
              <text x="161" y="173" textAnchor="middle" fontSize="7.5" fill="#7ea08c"
                    fontFamily="IBM Plex Mono, monospace" letterSpacing="1">SELL</text>
            </g>

            {/* ---- station 2 · signature ---- */}
            <g>
              <circle className="hf-seal" cx="476" cy="112" r="24" stroke="var(--green)" strokeWidth="1.6"
                      strokeDasharray="151" strokeDashoffset="151" fill="none" transform="rotate(-90 476 112)" />
              <text className="hf-seal-txt" x="476" y="109" textAnchor="middle" fontSize="8.5" fill="var(--green)"
                    fontFamily="IBM Plex Mono, monospace" fontWeight="600" opacity="0">SHA512</text>
              <text className="hf-seal-txt" x="476" y="121" textAnchor="middle" fontSize="8.5" fill="var(--green)"
                    fontFamily="IBM Plex Mono, monospace" fontWeight="600" opacity="0">· RSA ·</text>
              {/* pen: nib pointing down over the chit's path */}
              <g className="hf-pen">
                <path d="M427 88 l10 0 l-3 26 l-2 6 l-2 -6 z" fill="var(--ink)" />
                <rect x="426" y="78" width="12" height="10" rx="2" fill="var(--green)" />
              </g>
            </g>

            {/* ---- station 3 · MoR ---- */}
            <g>
              <path d="M655 112 L715 86 L775 112 Z" stroke="var(--ink)" strokeWidth="1.8" fill="none" />
              <text x="715" y="107" textAnchor="middle" fontSize="9.5" fill="var(--ink)"
                    fontFamily="IBM Plex Mono, monospace" fontWeight="700" letterSpacing="2">MOR</text>
              {[668, 696, 724, 752].map((x) => (
                <line key={x} x1={x} y1="116" x2={x} y2="148" stroke="var(--ink)" strokeWidth="2.4" />
              ))}
              <line x1="655" y1="150" x2="775" y2="150" stroke="var(--ink)" strokeWidth="2.2" />
              <rect className="hf-win" x="678" y="122" width="9" height="9" fill="var(--line)" />
              <rect className="hf-win" x="734" y="122" width="9" height="9" fill="var(--line)" />
              {/* wire down to the conveyor + pulses */}
              <line x1="715" y1="152" x2="715" y2="244" stroke="var(--line)" strokeWidth="1.4" strokeDasharray="3 5" />
              <circle className="hf-pulse-up" cx="715" cy="240" r="4" fill="var(--amber)" opacity="0" />
              <circle className="hf-pulse-dn" cx="715" cy="152" r="4" fill="var(--green)" opacity="0" />
              {/* sequence counter */}
              <text className="hf-ctr-old" x="800" y="132" fontSize="10" fill="var(--muted)"
                    fontFamily="IBM Plex Mono, monospace">№ 000048</text>
              <text className="hf-ctr-new" x="800" y="132" fontSize="10" fill="var(--green)" fontWeight="700"
                    fontFamily="IBM Plex Mono, monospace" opacity="0">№ 000049 ✓</text>
            </g>

            {/* ---- station 4 · phone ---- */}
            <g className="hf-phone" opacity="0">
              <g transform="rotate(7 1022 128)">
                <rect x="1000" y="88" width="44" height="80" rx="8" stroke="var(--ink)" strokeWidth="2" fill="var(--bg)" />
                <line x1="1014" y1="96" x2="1030" y2="96" stroke="var(--ink)" strokeWidth="1.6" />
                <text className="hf-phone-ok" x="1022" y="138" textAnchor="middle" fontSize="17" fill="var(--green)" fontWeight="700" opacity="0">✓</text>
              </g>
            </g>
            <line className="hf-beam" x1="1002" y1="146" x2="956" y2="206" stroke="var(--green)"
                  strokeWidth="1.6" strokeDasharray="5 5" opacity="0" />

            {/* ---- the traveling chit (drawn last = on top) ---- */}
            <g className="hf-chit" opacity="0">
              <rect x="0" y="0" width="62" height="80" fill="var(--paper)" stroke="var(--line)" strokeWidth="1.2" />
              {chitLine(7, 10, 55)}
              {chitLine(7, 17, 42)}
              {chitLine(7, 24, 55)}
              {/* signature — drawn at station 2 */}
              <path className="hf-sig" d="M9 68 q5 -9 10 0 t10 0 t10 0 q4 -7 9 -2"
                    stroke="#1a3f2c" strokeWidth="1.5" fill="none" strokeDasharray="66" strokeDashoffset="66" strokeLinecap="round" />
              <text className="hf-sealed" x="47" y="14" fontSize="6.5" fill="var(--green)" fontWeight="700"
                    fontFamily="IBM Plex Mono, monospace" opacity="0" textAnchor="middle">✎</text>
              {/* IRN chip — appears at station 3 */}
              <g className="hf-irn" opacity="0">
                <rect x="7" y="31" width="48" height="10" rx="2" fill="var(--green)" opacity="0.14" />
                <text x="31" y="39" textAnchor="middle" fontSize="7" fill="var(--green)" fontWeight="700"
                      fontFamily="IBM Plex Mono, monospace" letterSpacing="1">IRN·OK</text>
              </g>
              {/* QR — materializes at station 4 */}
              <g className="hf-qr">
                {QR_ON.map((on, i) =>
                  on ? (
                    <rect key={i} x={19 + (i % 5) * 5.2} y={44 + Math.floor(i / 5) * 4.6}
                          width="4" height="3.8" fill="#191d1a" />
                  ) : null
                )}
              </g>
            </g>

            {/* ---- the final stamp (over everything) ---- */}
            <g className="hf-stamp" opacity="0">
              <g transform="translate(948 150)">
                <circle r="30" stroke="var(--green)" strokeWidth="2.2" fill="var(--paper)" fillOpacity="0.88" />
                <circle r="24" stroke="var(--green)" strokeWidth="1" fill="none" strokeDasharray="3 3" />
                <text y="-4" textAnchor="middle" fontSize="8" fill="var(--green)" fontWeight="700"
                      fontFamily="IBM Plex Mono, monospace" letterSpacing="1">REGISTERED</text>
                <text y="7" textAnchor="middle" fontSize="7" fill="var(--green)" fontWeight="600"
                      fontFamily="IBM Plex Mono, monospace" letterSpacing="1">WITH MOR</text>
                <text y="19" textAnchor="middle" fontSize="10" fill="var(--green)" fontWeight="700">✓</text>
              </g>
            </g>
          </svg>
        </div>

        {/* ---------- step cards = progress rail ---------- */}
        <div className="hf-cards">
          {steps.map((s, i) => (
            <div key={s.n} className={"hf-card" + (active === i ? " is-active" : "")}>
              <div className="mono" style={{ color: "var(--green)", fontWeight: 600, fontSize: 13, letterSpacing: ".2em" }}>{s.n}</div>
              <div style={{ fontWeight: 900, fontSize: 22, textTransform: "uppercase", margin: "10px 0 8px" }}>{s.t}</div>
              <p style={{ color: "var(--paper-muted)", fontSize: 14.5 }}>{s.d}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
