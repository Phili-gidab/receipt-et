import { useLayoutEffect, useRef, useState } from "react";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { HERO_QR } from "../data/heroqr.js";
import { APP } from "../config.js";

gsap.registerPlugin(ScrollTrigger);

/**
 * slip.et-style hero: ONE continuous receipt fed out of a dark thermal bezel.
 * On load only the tail (totals + QR) peeks out; scrolling scrubs the paper
 * sliding down to the full Tsion Café bill. As it completes, the bezel flips
 * OFFLINE·QUEUED → ONLINE·SYNCED and "Registered with MoR" stamps in.
 * The slot window is sized to the paper's measured height so the zigzag tear
 * edge is never cropped at full extension.
 */

const BILL = {
  shop: "Tsion Café",
  addr: "Kazanchis, Addis Ababa",
  tin: "0012345678",
  vat: "45678901",
  no: "#INV-000482",
  date: "06/07/2026 · 14:22",
  items: [
    { name: "Macchiato", qty: 2, unit: 70, total: 140 },
    { name: "Kitfo special", qty: 1, unit: 250, total: 250 },
    { name: "Ambo water", qty: 1, unit: 40, total: 40 },
  ],
};
const TOTAL = BILL.items.reduce((s, i) => s + i.total, 0);
const PRE = +(TOTAL / 1.15).toFixed(2);
const VAT = +(TOTAL - PRE).toFixed(2);

export default function Hero() {
  const root = useRef(null);
  const slotRef = useRef(null);
  const paperRef = useRef(null);
  const [synced, setSynced] = useState(false);

  useLayoutEffect(() => {
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    // Slot = exactly the paper's height, so the tear edge shows fully at rest.
    const fit = () => {
      if (slotRef.current && paperRef.current) {
        slotRef.current.style.height = paperRef.current.offsetHeight + 14 + "px";
      }
    };
    fit();

    const ctx = gsap.context(() => {
      if (reduced) { setSynced(true); return; }
      gsap.set(".rcpt-registered", { autoAlpha: 0 });

      const feed = (tl, peek) => tl
        .fromTo(paperRef.current,
          { y: () => -(paperRef.current.offsetHeight - peek) },
          { y: 0, ease: "none", duration: 8 }, 0)
        .to(".rcpt-registered", { autoAlpha: 1, duration: 0.6 }, 7.2);

      const mm = gsap.matchMedia();

      // Desktop: pin the section, scrub the paper out while the page holds.
      mm.add("(min-width: 881px)", () => {
        const tl = gsap.timeline({
          scrollTrigger: {
            trigger: root.current,
            start: "top top",
            end: "+=75%",
            scrub: 0.35,
            pin: true,
            anticipatePin: 1,
            invalidateOnRefresh: true,
            onUpdate: (self) => setSynced(self.progress > 0.78),
          },
        });
        feed(tl, 330);
        tl.fromTo(".hero-copy", { yPercent: 0 }, { yPercent: -3, ease: "none", duration: 8 }, 0);
      });

      // Mobile: receipt stacks below the copy — no pin (it would print below
      // the fold). Scrub against the slot's own trip through the viewport.
      mm.add("(max-width: 880px)", () => {
        const tl = gsap.timeline({
          scrollTrigger: {
            trigger: slotRef.current,
            start: "top 82%",
            end: "top 18%",
            scrub: 0.35,
            invalidateOnRefresh: true,
            onUpdate: (self) => setSynced(self.progress > 0.78),
          },
        });
        feed(tl, Math.min(300, window.innerHeight * 0.4));
      });
    }, root);

    // Re-measure once webfonts land (metrics shift), then refresh triggers.
    if (document.fonts?.ready) {
      document.fonts.ready.then(() => { fit(); ScrollTrigger.refresh(); });
    }
    window.addEventListener("resize", fit);
    return () => { window.removeEventListener("resize", fit); ctx.revert(); };
  }, []);

  const row = { display: "flex", justifyContent: "space-between", gap: 8 };
  const nowrap = { whiteSpace: "nowrap" };
  const badge = { display: "inline-flex", alignItems: "center", gap: 7, whiteSpace: "nowrap" };

  return (
    <section ref={root} id="top" style={{ minHeight: "100vh", display: "flex", alignItems: "center", paddingTop: 70, overflow: "hidden" }}>
      <div className="container hero-grid">
        {/* ---- left copy ---- */}
        <div className="hero-copy" style={{ paddingTop: 44 }}>
          <div className="kicker">ADDIS ABABA · ETB <span className="dots" /> POINT OF SALE</div>
          <h1 style={{ fontWeight: 900, textTransform: "uppercase", letterSpacing: "-0.028em", lineHeight: 0.98, fontSize: "clamp(38px,5vw,72px)", margin: "24px 0 22px" }}>
            Every sale,
            <br />
            a compliant
            <br />
            <span style={{ color: "var(--green)", ...nowrap }}>
              fiscal receipt.<span style={{ display: "inline-block", width: ".4em", height: ".72em", background: "var(--green)", verticalAlign: "-0.05em", marginLeft: 8 }} />
            </span>
          </h1>
          <div className="pill" style={{ marginBottom: 24 }}>
            <span className="dot" /> Ethiopia is going QR-only. Be ready.
          </div>
          <p style={{ maxWidth: 520, color: "var(--muted)", fontSize: 17.5, marginBottom: 30 }}>
            Receipt is a cloud POS for Ethiopian businesses. Issue receipts with the
            QR code and invoice details required by the Ministry of Revenue — online
            or offline — and stay penalty-free.
          </p>
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginBottom: 28 }}>
            <a className="btn btn-solid" href={`${APP}/signup`}>Get started free</a>
            <a className="btn btn-ghost" href="#demo">See the real one</a>
          </div>
          <div className="mono" style={{ display: "flex", gap: 24, flexWrap: "wrap", fontSize: 11.5, letterSpacing: ".08em", color: "var(--muted)", textTransform: "uppercase" }}>
            <span style={badge}><span style={{ color: "var(--green)" }}>⛨</span> Designed for MoR compliance</span>
            <span style={badge}><span style={{ color: "var(--green)" }}>▦</span> Signed QR on every receipt</span>
            <span style={badge}><span style={{ color: "var(--green)" }}>⌁</span> Works fully offline</span>
          </div>
        </div>

        {/* ---- right: bezel + continuous paper feed ---- */}
        <div style={{ position: "relative", justifySelf: "center", width: "min(370px,94%)", marginTop: 16 }}>
          {/* bezel: thin, full-width status bar */}
          <div className="mono" style={{ position: "relative", zIndex: 3, background: "var(--bezel)", color: "#9fb0a3", fontSize: 10, letterSpacing: ".1em", padding: "13px 18px", borderRadius: 7, boxShadow: "0 14px 30px var(--shadow)", display: "flex", justifyContent: "space-between", gap: 18 }}>
            <span style={nowrap}>
              <span style={{ color: synced ? "#39d98a" : "var(--amber)" }}>●</span>{" "}
              {synced ? "ONLINE · SYNCED" : "OFFLINE · QUEUED"}
            </span>
            <span style={nowrap}>RECEIPT · THERMAL</span>
          </div>

          {/* slot window — narrower paper, emerges from under the bar */}
          <div ref={slotRef} style={{ margin: "-8px 24px 0", position: "relative", zIndex: 2, overflow: "hidden", height: 620 }}>
            <div ref={paperRef} className="paper tear-bottom" style={{ padding: "22px 20px 30px", willChange: "transform", fontSize: 13 }}>
              <div style={{ textAlign: "center", color: "var(--green)", fontSize: 18, lineHeight: 1 }}>🧾</div>
              <div style={{ textAlign: "center", fontFamily: "Archivo", fontWeight: 700, fontSize: 16.5, marginTop: 6 }}>{BILL.shop}</div>
              <div style={{ textAlign: "center", color: "var(--paper-muted)", fontSize: 11.5 }}>{BILL.addr}</div>
              <div style={{ textAlign: "center", color: "var(--paper-muted)", fontSize: 10.5, ...nowrap }}>TIN: {BILL.tin} · VAT: {BILL.vat}</div>
              <div className="dash-rule" />
              <div style={{ ...row, color: "var(--paper-muted)", fontSize: 11 }}>
                <span style={nowrap}>{BILL.no}</span><span style={nowrap}>{BILL.date}</span>
              </div>
              <div className="dash-rule" />
              {BILL.items.map((it, i) => (
                <div key={i} style={{ marginBottom: 9 }}>
                  <div style={row}>
                    <span style={{ fontWeight: 600 }}>{it.name}</span>
                    <span style={{ fontWeight: 600 }}>{it.total.toFixed(2)}</span>
                  </div>
                  <div style={{ color: "var(--paper-muted)", fontSize: 11 }}>{it.qty} × {it.unit.toFixed(2)}</div>
                </div>
              ))}
              <div className="dash-rule" />
              <div style={{ ...row, color: "var(--paper-muted)", fontSize: 12.5 }}><span>Subtotal</span><span>{PRE.toFixed(2)}</span></div>
              <div style={{ ...row, color: "var(--paper-muted)", fontSize: 12.5 }}><span>VAT 15%</span><span>{VAT.toFixed(2)}</span></div>
              <div style={{ ...row, fontWeight: 700, fontSize: 16, margin: "6px 0 2px" }}><span>Total</span><span style={nowrap}>ETB {TOTAL.toFixed(2)}</span></div>
              <div className="dash-rule" />
              <img src={`data:image/png;base64,${HERO_QR}`} alt="Demo QR" style={{ width: 116, height: 116, display: "block", margin: "6px auto 4px" }} />
              <div className="rcpt-registered" style={{ textAlign: "center", color: "var(--green)", fontWeight: 600, fontSize: 12, letterSpacing: ".04em" }}>
                ✓ Registered with MoR
              </div>
              <div style={{ textAlign: "center", color: "var(--paper-muted)", fontSize: 9.5, marginTop: 3, ...nowrap }}>
                IRN: RCPT-2026-TSN-000482
              </div>
            </div>
          </div>

          <div className="mono" style={{ textAlign: "center", marginTop: 14, fontSize: 10.5, letterSpacing: ".16em", color: "var(--muted)", ...nowrap }}>
            ↓ SCROLL — THE PRINTER IS FEEDING
          </div>
        </div>
      </div>
    </section>
  );
}
