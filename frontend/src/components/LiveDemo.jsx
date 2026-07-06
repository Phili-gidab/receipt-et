import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { RECEIPT } from "../data/receipt.js";
import { APP } from "../config.js";
import PrintReveal from "./PrintReveal.jsx";

const API_BASE = APP.replace(/\/app$/, "");
const delay = (ms) => new Promise((r) => setTimeout(r, ms));

const STEPS = [
  ["Signing invoice — SHA512withRSA, INSA certificate", 700],
  ["POST /v1/register → Ministry of Revenue EIMS", 1400],
  [`IRN + signed QR issued · sequence #${RECEIPT.docNo}`, 2100],
  ["POST /v1/receipt/sales → RRN issued", 2800],
];

export default function LiveDemo() {
  const [phase, setPhase] = useState("idle"); // idle | running | done
  const [lit, setLit] = useState(-1);
  const [live, setLive] = useState(null); // real just-registered doc, or null = replay

  const run = async () => {
    if (phase === "running") return;
    setPhase("running"); setLit(-1); setLive(null);
    STEPS.forEach((_, i) => setTimeout(() => setLit(i), 500 + i * 700));
    // fire a REAL sandbox registration; fall back to the stored replay if the
    // backend is unreachable (e.g. https page calling the http sandbox host)
    const charge = fetch(`${API_BASE}/demo/charge`, { method: "POST" })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => (d && d.ok ? d : null))
      .catch(() => null);
    const [result] = await Promise.all([charge, delay(600 + STEPS.length * 700)]);
    setLive(result);
    setPhase("done");
  };

  const R = live || RECEIPT;

  const row = { display: "flex", justifyContent: "space-between" };

  return (
    <section id="demo" className="section">
      <div className="container">
        <div className="kicker">LIVE DEMO <span className="dots" /> NO MOCKUPS</div>
        <PrintReveal className="h2">Press charge. <em>Watch it become official.</em></PrintReveal>
        <p style={{ color: "var(--muted)", maxWidth: 560, marginBottom: 40 }}>
          The receipt below was genuinely registered in the Ministry of Revenue's EIMS
          sandbox by this platform. Same engine, same cryptography as production.
        </p>

        <div className="split-demo">
          {/* cashier side */}
          <div style={{ border: "1.5px dashed var(--line)", padding: 26, background: "var(--paper)", color: "var(--paper-ink)" }}>
            <div className="mono" style={{ fontSize: 11, letterSpacing: ".2em", color: "var(--green)", marginBottom: 16 }}>POINT OF SALE — CASHIER VIEW</div>
            {RECEIPT.items.map((it, i) => (
              <div key={i} className="mono" style={{ ...row, padding: "10px 0", borderBottom: "1px dashed #d8d3c2", fontSize: 13.5 }}>
                <span>{it.name}<span style={{ color: "var(--paper-muted)", fontSize: 11, display: "block" }}>{it.qty} × {it.unit.toFixed(2)}</span></span>
                <b>{it.total.toFixed(2)}</b>
              </div>
            ))}
            <div className="mono" style={{ ...row, padding: "9px 0", color: "var(--paper-muted)", fontSize: 13 }}><span>Subtotal</span><span>{RECEIPT.preTax.toFixed(2)}</span></div>
            <div className="mono" style={{ ...row, padding: "0 0 9px", color: "var(--paper-muted)", fontSize: 13 }}><span>VAT 15%</span><span>{RECEIPT.vat.toFixed(2)}</span></div>
            <div className="mono" style={{ ...row, borderTop: "2px solid var(--paper-ink)", paddingTop: 12, fontWeight: 700, fontSize: 17 }}>
              <span>TOTAL</span><span>ETB {RECEIPT.total.toFixed(2)}</span>
            </div>
            <button className="btn btn-solid" onClick={run} disabled={phase === "running"}
                    style={{ width: "100%", justifyContent: "center", marginTop: 20, background: phase === "done" ? "var(--green-deep)" : undefined }}>
              {phase === "idle" && "Charge & issue fiscal receipt"}
              {phase === "running" && "Registering with MoR…"}
              {phase === "done" && "✓ Receipt issued — scan the QR"}
            </button>
            <div className="mono" style={{ marginTop: 16, fontSize: 12, color: "var(--muted)" }}>
              {STEPS.map(([label], i) => (
                <div key={i} style={{ padding: "4px 0", opacity: lit >= i ? 1 : 0.3, color: lit >= i ? "var(--ink)" : undefined, transition: "opacity .3s" }}>
                  <span style={{ color: "var(--green)" }}>→</span> {label}
                </div>
              ))}
            </div>
          </div>

          {/* receipt side */}
          <div style={{ position: "relative", minHeight: 420 }}>
            <AnimatePresence>
              {phase === "done" ? (
                <motion.div key="paper" initial={{ y: 26, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={{ type: "spring", bounce: 0.25, duration: 0.7 }}
                            className="paper tear-bottom" style={{ padding: "24px 22px 30px", maxWidth: 360, margin: "0 auto" }}>
                  <div style={{ textAlign: "center", fontFamily: "Archivo", fontWeight: 700, fontSize: 16 }}>DELTA AESTHETICS</div>
                  <div style={{ textAlign: "center", color: "var(--paper-muted)", fontSize: 11 }}>TIN: 0107184904 · pilot merchant (sandbox)</div>
                  <div className="dash-rule" />
                  <div style={{ ...row, color: "var(--paper-muted)", fontSize: 12 }}>
                    <span>Doc #{R.docNo}</span><span>{(R.date || "").slice(0, 10)}</span>
                  </div>
                  {R.items.map((it, i) => (
                    <div key={i} style={{ ...row, fontWeight: 600, marginTop: 8 }}><span>{it.name}</span><span>{it.total.toFixed(2)}</span></div>
                  ))}
                  <div className="dash-rule" />
                  <div style={{ ...row, color: "var(--paper-muted)", fontSize: 12.5 }}><span>Subtotal</span><span>{R.preTax.toFixed(2)}</span></div>
                  <div style={{ ...row, color: "var(--paper-muted)", fontSize: 12.5 }}><span>VAT 15%</span><span>{R.vat.toFixed(2)}</span></div>
                  <div style={{ ...row, fontWeight: 700, fontSize: 15.5, marginTop: 4 }}><span>TOTAL</span><span>ETB {R.total.toFixed(2)}</span></div>
                  <div className="dash-rule" />
                  <img src={`data:image/png;base64,${R.qr}`} alt="Real MoR QR" style={{ width: 140, height: 140, display: "block", margin: "6px auto" }} />
                  <div style={{ textAlign: "center", color: "var(--green)", fontWeight: 600, fontSize: 12, letterSpacing: ".08em" }}>
                    ✓ REGISTERED WITH MINISTRY OF REVENUE{live ? " — JUST NOW" : ""}
                  </div>
                  <div style={{ textAlign: "center", color: "var(--paper-muted)", fontSize: 10, marginTop: 4 }}>
                    {live
                      ? "This receipt was created seconds ago — refresh the MoR portal and it's there."
                      : "Registered 6 Jul 2026 in the MoR sandbox by this platform."}
                  </div>
                  <div style={{ fontSize: 8.5, color: "var(--paper-muted)", wordBreak: "break-all", textAlign: "center", marginTop: 6 }}>IRN {R.irn}</div>
                  {R.rrn && <div style={{ fontSize: 8.5, color: "var(--paper-muted)", wordBreak: "break-all", textAlign: "center" }}>RRN {R.rrn}</div>}
                </motion.div>
              ) : (
                <motion.div key="hint" exit={{ opacity: 0 }}
                            style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", border: "1.5px dashed var(--line)", color: "var(--muted)" }}
                            className="mono">
                  <span style={{ fontSize: 12.5, letterSpacing: ".14em" }}>{phase === "running" ? "PRINTING…" : "THE FISCAL RECEIPT APPEARS HERE"}</span>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>
      </div>
    </section>
  );
}
