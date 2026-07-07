import { useLayoutEffect, useRef, useState } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import PrintReveal from "./PrintReveal.jsx";

gsap.registerPlugin(ScrollTrigger);

/**
 * HOW IT WORKS — "follow one sale".
 * An SVG assembly line: a receipt chit is printed at the POS, carried on a
 * conveyor belt through a plotter-style signing arm, up-linked to the MoR
 * building, and finally swept by a verification gate that stamps it. Desktop
 * pins the section and scroll scrubs the journey; mobile autoplays on a
 * swipeable strip. The four step cards double as a progress rail, and each
 * station is centered on its card's column.
 */

const steps = [
  { n: "01", t: "Sell", d: "Ring up the sale on the web POS — phone, tablet or desktop. Amharic-friendly, keyboard-fast, cashier-simple." },
  { n: "02", t: "Sign", d: "Each invoice is canonically serialized and signed SHA512-RSA with an INSA-issued digital certificate. Keys never leave the server." },
  { n: "03", t: "Register", d: "Sent to MoR EIMS in real time. Sequence-chained per business — no invoice can be skipped, duplicated or forged." },
  { n: "04", t: "Verify", d: "MoR returns the IRN and a government-signed QR. Print thermal or A4; anyone can scan and verify the sale instantly." },
];

/* fixed pseudo-QR pattern (5×5) so the modules are stable between renders */
const QR_ON = [1,1,1,0,1, 1,0,1,1,0, 1,1,0,1,1, 0,1,1,0,1, 1,0,1,1,1];
const PQR_ON = [1,0,1, 0,1,1, 1,1,0]; /* phone screen mini-QR */

/* deep green for marks that sit ON cream paper — the bright theme green
   washes out on the chit/cards (1.85:1); this holds 4.5:1 on cream */
const PG = "#0e7a4e";

/* chit x waypoints (left edge of the 70-wide chit), centered on card columns */
const CHIT_X = [118, 353, 618, 884];
const LABELS = [
  { x: 135, t: "01 · SELL", d: "WEB POS" },
  { x: 390, t: "02 · SIGN", d: "SHA512·RSA + INSA" },
  { x: 655, t: "03 · REGISTER", d: "MOR EIMS · SEQUENCED" },
  { x: 921, t: "04 · VERIFY", d: "SIGNED QR · IRN" },
];

/* zigzag-bottom receipt outline, 70×100 */
const CHIT_PATH =
  "M0 0 H70 V94 L64.2 100 L58.3 94 L52.5 100 L46.7 94 L40.8 100 L35 94 " +
  "L29.2 100 L23.3 94 L17.5 100 L11.7 94 L5.8 100 L0 94 Z";

function buildTimeline(q) {
  const tl = gsap.timeline({ defaults: { ease: "power2.inOut" } });
  /* a small arrival "clunk" as the chit docks at a station */
  const dip = (t) => {
    tl.to(q(".hf-chit"), { y: 169, duration: 0.12, ease: "power2.out" }, t)
      .to(q(".hf-chit"), { y: 166, duration: 0.14, ease: "power2.in" }, t + 0.12);
  };

  /* gsap owns the chit transform outright (SVG translate would be replaced,
     not composed) — position it explicitly from frame 0 */
  tl.set(q(".hf-chit"), { x: CHIT_X[0], y: 166 }, 0);

  /* belt marches for the entire journey */
  tl.to(q(".hf-belt"), { strokeDashoffset: -288, duration: 16, ease: "none" }, 0);

  /* ---- scene 1 · SELL (0 → 2.2) ---- */
  tl.to(q(".hf-screenclip"), { attr: { width: 130 }, duration: 1.1, ease: "none" }, 0.15)
    .fromTo(q(".hf-key-sell"), { fill: "#1c2420" }, { fill: "var(--green)", duration: 0.18, yoyo: true, repeat: 1 }, 1.3)
    .fromTo(q(".hf-beep"), { attr: { r: 6 }, autoAlpha: 0.9 },
            { attr: { r: 24 }, autoAlpha: 0, duration: 0.5, ease: "power1.out", immediateRender: false }, 1.32)
    /* the screen dims once the receipt is printed — visual weight moves on with the story */
    .to(q(".hf-screen"), { opacity: 0.3, duration: 0.5 }, 1.55)
    .fromTo(q(".hf-chit"), { autoAlpha: 0, y: 146 }, { autoAlpha: 1, y: 166, duration: 0.65, ease: "back.out(1.4)" }, 1.55);

  /* ---- travel 1 (2.2 → 3.6) ---- */
  tl.to(q(".hf-chit"), { x: CHIT_X[1], duration: 1.4, ease: "power1.inOut" }, 2.2)
    .to(q(".hf-chit"), { rotation: 1.6, transformOrigin: "50% 100%", duration: 0.7, yoyo: true, repeat: 1, ease: "sine.inOut" }, 2.2);
  dip(3.6);

  /* ---- scene 2 · SIGN (3.6 → 6.2): the arm writes on the paper ---- */
  tl.to(q(".hf-pen"), { y: 49, x: -21, duration: 0.5, ease: "power2.in" }, 3.75)
    .to(q(".hf-ink"), { attr: { r: 1.8 }, duration: 0.12 }, 4.25)
    .to(q(".hf-sig"), { strokeDashoffset: 0, duration: 1.2, ease: "power1.inOut" }, 4.3)
    .to(q(".hf-pen"), { x: 17, duration: 1.2, ease: "power1.inOut" }, 4.3)
    .to(q(".hf-seal"), { strokeDashoffset: 0, duration: 1.0, ease: "power1.inOut" }, 4.4)
    .fromTo(q(".hf-seal-txt"), { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.35 }, 5.25)
    .to(q(".hf-pen"), { y: 0, x: 0, duration: 0.5, ease: "power2.out" }, 5.55)
    .fromTo(q(".hf-sealchip"), { autoAlpha: 0, scale: 0, transformOrigin: "50% 50%" },
            { autoAlpha: 1, scale: 1, duration: 0.4, ease: "back.out(2.2)" }, 5.65)
    .fromTo(q(".hf-sealed"), { autoAlpha: 0, scale: 1.6, transformOrigin: "50% 50%" },
            { autoAlpha: 1, scale: 1, duration: 0.4, ease: "back.out(2)" }, 5.8);

  /* ---- travel 2 (6.2 → 7.4) ---- */
  tl.to(q(".hf-chit"), { x: CHIT_X[2], duration: 1.2, ease: "power1.inOut" }, 6.2)
    .to(q(".hf-chit"), { rotation: -1.4, duration: 0.6, yoyo: true, repeat: 1, ease: "sine.inOut" }, 6.2)
    /* the seal badges belong to the receipt now — dim the station remnants */
    .to([...q(".hf-seal"), ...q(".hf-seal-txt"), ...q(".hf-sealed")], { opacity: 0.3, duration: 0.5 }, 6.4);
  dip(7.4);

  /* ---- scene 3 · REGISTER (7.4 → 10.6): packets up, answer down ---- */
  q(".hf-pkt-up").forEach((p, i) => {
    tl.fromTo(p, { autoAlpha: 0, y: 0, x: 0 }, { autoAlpha: 1, y: -46, x: 5, duration: 0.32, ease: "power1.in" }, 7.55 + i * 0.28)
      .to(p, { autoAlpha: 0, y: -82, x: 10, duration: 0.3, ease: "power1.out" }, 7.87 + i * 0.28);
  });
  tl.to(q(".hf-win"), { fill: "var(--amber)", duration: 0.15, yoyo: true, repeat: 3, stagger: 0.07 }, 8.5)
    .to(q(".hf-win"), { fill: "var(--green)", duration: 0.28, stagger: 0.07 }, 9.15)
    .fromTo(q(".hf-pkt-dn"), { autoAlpha: 0, y: -82 }, { autoAlpha: 1, y: 0, duration: 0.5, ease: "power1.in" }, 9.4)
    .to(q(".hf-pkt-dn"), { autoAlpha: 0, duration: 0.15 }, 9.9)
    .to(q(".hf-ctr-old"), { autoAlpha: 0, y: -9, duration: 0.32 }, 9.6)
    .fromTo(q(".hf-ctr-new"), { autoAlpha: 0, y: 9 }, { autoAlpha: 1, y: 0, duration: 0.32 }, 9.7)
    .fromTo(q(".hf-irn"), { autoAlpha: 0, scale: 0, transformOrigin: "50% 50%" },
            { autoAlpha: 1, scale: 1, duration: 0.45, ease: "back.out(2.4)" }, 10.1);

  /* ---- travel 3 (10.6 → 11.8) ---- */
  tl.to(q(".hf-chit"), { x: CHIT_X[3], duration: 1.2, ease: "power1.inOut" }, 10.6)
    .to(q(".hf-chit"), { rotation: 1.4, duration: 0.6, yoyo: true, repeat: 1, ease: "sine.inOut" }, 10.6);
  dip(11.8);

  /* ---- scene 4 · VERIFY (11.8 → 16): gate sweep, stamp, phone wakes ---- */
  tl.to(q(".hf-pscreen"), { fill: "#0f3320", duration: 0.4 }, 12.0)
    .fromTo(q(".hf-pqr"), { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.35, stagger: 0.04 }, 12.1)
    .fromTo(q(".hf-scan"), { autoAlpha: 0 }, { autoAlpha: 0.9, duration: 0.2 }, 12.2)
    .to(q(".hf-scan"), { attr: { y1: 252, y2: 252 }, duration: 1.2, ease: "power1.inOut" }, 12.25)
    .to(q(".hf-scan"), { autoAlpha: 0, duration: 0.25 }, 13.45)
    .fromTo(q(".hf-qr rect"), { scale: 0, transformOrigin: "50% 50%" },
            { scale: 1, duration: 0.26, stagger: { each: 0.028, from: "start" }, ease: "back.out(2)" }, 12.35)
    .fromTo(q(".hf-stamp"), { autoAlpha: 0, scale: 2.4, rotation: -24, transformOrigin: "50% 50%" },
            { autoAlpha: 1, scale: 1, rotation: -9, duration: 0.7, ease: "back.out(1.9)" }, 14.2)
    /* the paper's own header recedes where the ink lands */
    .to(q(".hf-chitink"), { opacity: 0.4, duration: 0.4 }, 14.3);
  q(".hf-spark").forEach((s, i) => {
    tl.fromTo(s, { autoAlpha: 0, scale: 0, transformOrigin: "50% 50%" },
              { autoAlpha: 1, scale: 1, duration: 0.22, ease: "back.out(3)" }, 14.55 + i * 0.12)
      .to(s, { autoAlpha: 0, duration: 0.3 }, 14.95 + i * 0.12);
  });
  tl.fromTo(q(".hf-phone-ok"), { autoAlpha: 0, scale: 0, transformOrigin: "50% 50%" },
            { autoAlpha: 1, scale: 1, duration: 0.4, ease: "back.out(2.6)" }, 14.95)
    .to(q(".hf-pqr"), { autoAlpha: 0.25, duration: 0.3 }, 14.95)
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

  const mono = "IBM Plex Mono, monospace";

  return (
    <section ref={root} id="how" className="section"
             style={{ background: "var(--bg-2)", overflow: "hidden", padding: "clamp(48px,6vw,84px) 0 44px" }}>
      <div className="container">
        <div className="kicker">HOW IT WORKS <span className="dots" /> FOLLOW ONE SALE</div>
        <PrintReveal className="h2">From “thank you”<br />to <em>tax-office truth.</em></PrintReveal>

        {/* ---------- SVG assembly line ---------- */}
        <div className="howflow-wrap">
          <svg className="howflow" viewBox="0 0 1060 330" fill="none" role="img"
               aria-label="A receipt travels a conveyor from the POS, is signed by a machine arm, registered with the Ministry of Revenue and swept by a verification gate that stamps it.">

            {/* ---- conveyor belt + rollers ---- */}
            <line className="hf-belt" x1="36" y1="268" x2="1024" y2="268" stroke="var(--line)" strokeWidth="2.2" strokeDasharray="10 8" />
            <line className="hf-belt" x1="36" y1="278" x2="1024" y2="278" stroke="var(--line)" strokeWidth="1.4" strokeDasharray="10 8" />
            {Array.from({ length: 11 }, (_, i) => 60 + i * 96).map((x) => (
              <circle key={x} cx={x} cy="286" r="4.5" stroke="var(--line)" strokeWidth="1.5" />
            ))}

            {/* labels + descriptors */}
            {LABELS.map((l, i) => (
              <g key={l.x} fontFamily={mono}>
                <text x={l.x} y="308" textAnchor="middle" fontSize="11" letterSpacing="2"
                      fill={active === i ? "var(--green)" : "var(--muted)"} style={{ transition: "fill .3s" }}>
                  {l.t}
                </text>
                <text x={l.x} y="323" textAnchor="middle" fontSize="8" letterSpacing="1.2" fill="var(--muted)">
                  {l.d}
                </text>
              </g>
            ))}

            {/* ---- station 1 · POS terminal (grounded on the belt) ---- */}
            <g>
              <rect x="58" y="128" width="154" height="136" rx="10" fill="var(--bezel)" stroke="var(--muted)" strokeOpacity="0.45" strokeWidth="1" />
              <rect x="70" y="140" width="130" height="52" rx="4" fill="#1c2420" />
              <clipPath id="hfScreenClip"><rect className="hf-screenclip" x="70" y="140" width="0" height="52" /></clipPath>
              <g className="hf-screen" clipPath="url(#hfScreenClip)" fontFamily={mono}>
                <text x="78" y="158" fontSize="9.5" fill="#cfe8d8">MACCHIATO</text>
                <text x="192" y="158" fontSize="9.5" fill="#cfe8d8" textAnchor="end">100.00</text>
                <text x="78" y="178" fontSize="9.5" fill="#39d98a" fontWeight="600">TOTAL</text>
                <text x="192" y="178" fontSize="9.5" fill="#39d98a" textAnchor="end" fontWeight="600">ETB 100.00</text>
              </g>
              <rect x="70" y="200" width="26" height="18" rx="3" fill="#1c2420" />
              <rect x="102" y="200" width="26" height="18" rx="3" fill="#1c2420" />
              <rect x="134" y="200" width="26" height="18" rx="3" fill="#1c2420" />
              <circle cx="196" cy="209" r="3" fill="#39d98a" className="hf-led" />
              <rect className="hf-key-sell" x="70" y="226" width="130" height="22" rx="3" fill="#1c2420" />
              <text x="135" y="241" textAnchor="middle" fontSize="9" fill="#7ea08c" fontFamily={mono} letterSpacing="3">SELL</text>
              <circle className="hf-beep" cx="135" cy="237" r="6" stroke="var(--green)" strokeWidth="1.6" opacity="0" />
            </g>

            {/* ---- station 2 · plotter signing arm (centered on card 2) ---- */}
            <g transform="translate(-47 0)">
              <rect x="472" y="260" width="20" height="8" fill="var(--ink)" />
              <line x1="482" y1="262" x2="482" y2="108" stroke="var(--ink)" strokeWidth="3" />
              <line x1="506" y1="112" x2="418" y2="112" stroke="var(--ink)" strokeWidth="3" />
              <rect x="498" y="104" width="12" height="14" fill="var(--ink)" />
              <line x1="482" y1="140" x2="444" y2="113" stroke="var(--ink)" strokeWidth="1.8" />
              {/* dashed docking pad — where the paper parks under the nib */}
              <line x1="400" y1="264" x2="470" y2="264" stroke="var(--muted)" strokeWidth="1.6" strokeDasharray="3 3" opacity="0.6" />
              {/* the pen carriage: tucked against the beam at rest */}
              <g className="hf-pen">
                <rect x="423" y="112" width="16" height="12" rx="2" fill="var(--ink)" />
                <rect x="426" y="124" width="10" height="20" rx="3" fill="var(--green)" />
                <line x1="434" y1="126" x2="434" y2="134" stroke="var(--bezel)" strokeWidth="1.6" />
                <rect x="426" y="144" width="10" height="6" fill="var(--ink)" />
                <path d="M426 150 L436 150 L431 162 Z" fill="var(--ink)" />
              </g>
              {/* certificate seal hanging off the post */}
              <circle className="hf-seal" cx="518" cy="128" r="22" stroke="var(--green)" strokeWidth="1.8"
                      strokeDasharray="140" strokeDashoffset="140" transform="rotate(-90 518 128)" />
              <g className="hf-seal-txt" fontFamily={mono} fontWeight="600" opacity="0">
                <text x="518" y="126" textAnchor="middle" fontSize="8" fill="var(--green)">SHA512</text>
                <text x="518" y="137" textAnchor="middle" fontSize="8" fill="var(--green)">· RSA ·</text>
              </g>
              <g className="hf-sealed" opacity="0" fontFamily={mono}>
                <rect x="494" y="158" width="50" height="14" stroke="var(--green)" strokeWidth="1.2" strokeDasharray="3 2.4" />
                <text x="519" y="168" textAnchor="middle" fontSize="7.5" fill="var(--green)" fontWeight="700" letterSpacing="1">SEALED ✓</text>
              </g>
            </g>

            {/* ---- station 3 · MoR building (centered on card 3) ---- */}
            <g transform="translate(-47 0)">
              <rect x="642" y="258" width="146" height="8" stroke="var(--ink)" strokeWidth="1.8" />
              <rect x="650" y="250" width="130" height="8" stroke="var(--ink)" strokeWidth="1.8" />
              <rect x="658" y="242" width="114" height="8" stroke="var(--ink)" strokeWidth="1.8" />
              <line x1="652" y1="150" x2="778" y2="150" stroke="var(--ink)" strokeWidth="2.6" />
              {[668, 700, 732, 764].map((x) => (
                <line key={x} x1={x} y1="154" x2={x} y2="242" stroke="var(--ink)" strokeWidth="2.6" />
              ))}
              <path d="M638 150 L715 100 L792 150 Z" stroke="var(--ink)" strokeWidth="2.2" />
              <text x="715" y="142" textAnchor="middle" fontSize="10" fill="var(--ink)" fontFamily={mono} fontWeight="700" letterSpacing="2.5">MOR</text>
              <rect x="707" y="206" width="18" height="36" stroke="var(--ink)" strokeWidth="1.8" />
              <rect className="hf-win" x="676" y="186" width="12" height="12" fill="var(--line)" />
              <rect className="hf-win" x="742" y="186" width="12" height="12" fill="var(--line)" />
              {/* antenna the packets fly to */}
              <line x1="715" y1="100" x2="715" y2="72" stroke="var(--ink)" strokeWidth="2" />
              <circle cx="715" cy="67" r="3.5" fill="var(--green)" className="hf-led" />
              {/* data packets (animated relative to their start) */}
              {[0, 1, 2].map((i) => (
                <rect key={i} className="hf-pkt-up" x="697" y="158" width="5.5" height="5.5" fill="var(--amber)" opacity="0" />
              ))}
              <rect className="hf-pkt-dn" x="708" y="158" width="5.5" height="5.5" fill="var(--green)" opacity="0" />
              {/* "now serving" sequence counter on its own post */}
              <line x1="838" y1="266" x2="838" y2="178" stroke="var(--ink)" strokeWidth="2.6" />
              <rect x="800" y="150" width="76" height="30" rx="3" stroke="var(--ink)" strokeWidth="1.8" fill="var(--bg-2)" />
              <text x="838" y="161" textAnchor="middle" fontSize="5.8" fill="var(--muted)" fontFamily={mono} letterSpacing="1.6">NOW SERVING</text>
              <text className="hf-ctr-old" x="838" y="174" textAnchor="middle" fontSize="10" fill="var(--muted)" fontFamily={mono}>000048</text>
              <text className="hf-ctr-new" x="838" y="174" textAnchor="middle" fontSize="10" fill="var(--green)" fontWeight="700" fontFamily={mono} opacity="0">000049</text>
            </g>

            {/* ---- station 4 · verification gate + phone leaning on it ---- */}
            <g transform="translate(-18 0)">
              <line x1="892" y1="266" x2="892" y2="118" stroke="var(--ink)" strokeWidth="3" />
              <line x1="992" y1="266" x2="992" y2="118" stroke="var(--ink)" strokeWidth="3" />
              <line x1="890" y1="118" x2="994" y2="118" stroke="var(--ink)" strokeWidth="3" />
              <line x1="892" y1="140" x2="912" y2="119" stroke="var(--ink)" strokeWidth="1.6" />
              <line x1="992" y1="140" x2="972" y2="119" stroke="var(--ink)" strokeWidth="1.6" />
              <rect x="928" y="118" width="28" height="14" rx="2" fill="var(--bezel)" stroke="var(--muted)" strokeOpacity="0.55" strokeWidth="1" />
              <circle cx="942" cy="137" r="4" fill="var(--green)" className="hf-lens" />
              {/* faint idle scanline so the gate self-identifies as a scanner */}
              <line x1="896" y1="150" x2="988" y2="150" stroke="var(--green)" strokeWidth="1.2" strokeDasharray="5 4" opacity="0.16" />
              <line className="hf-scan" x1="896" y1="150" x2="988" y2="150" stroke="var(--green)"
                    strokeWidth="1.8" strokeDasharray="5 4" opacity="0" />
              {/* phone leaning against the gate's right post, feet on the belt */}
              <ellipse cx="1016" cy="266" rx="24" ry="3.2" fill="#000" opacity="0.15" />
              <g transform="rotate(-8 1016 262)">
                <rect x="996" y="190" width="40" height="72" rx="7" stroke="var(--ink)" strokeWidth="2" fill="var(--bg)" />
                <rect className="hf-pscreen" x="1001" y="198" width="30" height="50" rx="3" fill="#101511" />
                {PQR_ON.map((on, i) =>
                  on ? (
                    <rect key={i} className="hf-pqr" x={1007 + (i % 3) * 6.2} y={205 + Math.floor(i / 3) * 6.2}
                          width="4.6" height="4.6" fill="#39d98a" opacity="0" />
                  ) : null
                )}
                <text className="hf-phone-ok" x="1016" y="242" textAnchor="middle" fontSize="17" fill="#39d98a" fontWeight="700" opacity="0">✓</text>
                <line x1="1010" y1="255" x2="1022" y2="255" stroke="var(--ink)" strokeWidth="1.6" />
              </g>
            </g>

            {/* ---- the traveling chit (drawn last = on top) ---- */}
            <g className="hf-chit" opacity="0">
              <ellipse cx="35" cy="101" rx="32" ry="3.4" fill="#000" opacity="0.16" />
              <path d={CHIT_PATH} fill="var(--paper)" stroke="var(--line)" strokeWidth="1.2" />
              <g className="hf-chitink">
                <text x="35" y="12" textAnchor="middle" fontSize="6.5" fill="#63695f" fontFamily={mono} letterSpacing="2">RECEIPT</text>
                <line x1="8" y1="16" x2="62" y2="16" stroke="#c4bfae" strokeWidth="1" strokeDasharray="2 2" />
                <line x1="8" y1="24" x2="60" y2="24" stroke="#c4bfae" strokeWidth="1.6" />
                <line x1="8" y1="31" x2="46" y2="31" stroke="#c4bfae" strokeWidth="1.6" />
              </g>
              {/* signature — inked by the arm at station 2 */}
              <path className="hf-sig" d="M9 46 q5 -9 10 0 t10 0 t10 0 q4 -7 9 -2"
                    stroke="#1a3f2c" strokeWidth="1.5" strokeDasharray="72" strokeDashoffset="72" strokeLinecap="round" />
              <circle className="hf-ink" cx="10" cy="45" r="0" fill="#1a3f2c" />
              <g className="hf-sealchip" opacity="0">
                <circle cx="58" cy="42" r="6" stroke={PG} strokeWidth="1.4" fill="var(--paper)" />
                <text x="58" y="45" textAnchor="middle" fontSize="6.5" fill={PG} fontWeight="700">✓</text>
              </g>
              {/* IRN chip — station 3 */}
              <g className="hf-irn" opacity="0">
                <rect x="9" y="53" width="52" height="11" rx="2" fill={PG} opacity="0.13" />
                <text x="35" y="61.5" textAnchor="middle" fontSize="7" fill={PG} fontWeight="700"
                      fontFamily={mono} letterSpacing="1">IRN·OK</text>
              </g>
              {/* QR — station 4 */}
              <g className="hf-qr">
                {QR_ON.map((on, i) =>
                  on ? (
                    <rect key={i} x={20.5 + (i % 5) * 5.6} y={68 + Math.floor(i / 5) * 4.9}
                          width="4.4" height="4.1" fill="#191d1a" />
                  ) : null
                )}
              </g>
            </g>

            {/* ---- the final stamp + sparks (ink-only, clipped to the paper) ---- */}
            {[[887, 138], [960, 152], [944, 116], [881, 196]].map(([x, y], i) => (
              <text key={i} className="hf-spark" x={x} y={y} fontSize="13" fill="var(--green)" fontWeight="700" opacity="0">+</text>
            ))}
            <clipPath id="hfStampClip"><rect x={CHIT_X[3]} y="166" width="70" height="100" /></clipPath>
            <g clipPath="url(#hfStampClip)">
            <g className="hf-stamp" opacity="0">
              <g transform="translate(919 184)">
                <circle r="29" stroke={PG} strokeWidth="2.4" />
                <circle r="23" stroke={PG} strokeWidth="1" strokeDasharray="3 3" />
                <text y="-4" textAnchor="middle" fontSize="7.5" fill={PG} fontWeight="700" fontFamily={mono} letterSpacing="1">REGISTERED</text>
                <text y="6" textAnchor="middle" fontSize="6.5" fill={PG} fontWeight="600" fontFamily={mono} letterSpacing="1">WITH MOR</text>
                <text y="18" textAnchor="middle" fontSize="10" fill={PG} fontWeight="700">✓</text>
              </g>
            </g>
            </g>
          </svg>
        </div>

        {/* ---------- step cards = progress rail ---------- */}
        <div className="hf-cards">
          {steps.map((s, i) => (
            <div key={s.n} className={"hf-card" + (active === i ? " is-active" : "")}>
              <div className="mono" style={{ color: PG, fontWeight: 600, fontSize: 13, letterSpacing: ".2em" }}>{s.n}</div>
              <div style={{ fontWeight: 900, fontSize: 22, textTransform: "uppercase", margin: "10px 0 8px" }}>{s.t}</div>
              <p style={{ color: "var(--paper-muted)", fontSize: 14.5 }}>{s.d}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
