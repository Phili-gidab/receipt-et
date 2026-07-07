import { motion } from "framer-motion";
import PrintReveal from "./PrintReveal.jsx";

const checks = [
  "Issue receipts with zero connectivity",
  "Contingency copy customers can keep",
  "Automatic, in-order sync when online",
  "Sequence chain kept intact, nothing skipped",
];

export default function Offline() {
  return (
    <section id="offline" className="section" style={{ background: "var(--bg-2)" }}>
      <div className="container split-offline">
        {/* contingency-mode card */}
        <motion.div initial={{ opacity: 0, y: 24 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: "-60px" }} transition={{ duration: 0.55 }}
          style={{ position: "relative", border: "1.5px dashed var(--line)", padding: "44px 28px 28px", background: "var(--paper)", color: "var(--paper-ink)" }}>
          <span className="stamp amber" style={{ left: 18, right: "auto", transform: "rotate(-4deg)" }}>Contingency mode</span>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 20 }}>
            <div style={{ textAlign: "center" }}>
              <div style={{ width: 58, height: 58, background: "var(--bezel)", color: "var(--amber)", display: "grid", placeItems: "center", fontSize: 22, borderRadius: 8 }}>⌁</div>
              <div className="mono" style={{ fontSize: 10, letterSpacing: ".14em", marginTop: 8, color: "var(--paper-muted)" }}>NETWORK DOWN</div>
            </div>
            <div className="mono" style={{ flex: 1, borderTop: "2px dashed var(--line)", position: "relative", top: -12 }} />
            <div className="mono" style={{ color: "var(--green)", fontSize: 18, position: "relative", top: -14 }}>⟳</div>
            <div className="mono" style={{ flex: 1, borderTop: "2px dashed var(--line)", position: "relative", top: -12 }} />
            <div style={{ textAlign: "center" }}>
              <div style={{ width: 58, height: 58, background: "var(--bezel)", color: "#39d98a", display: "grid", placeItems: "center", fontSize: 22, borderRadius: 8 }}>◷</div>
              <div className="mono" style={{ fontSize: 10, letterSpacing: ".14em", marginTop: 8, color: "var(--paper-muted)" }}>AUTO-SYNCS LATER</div>
            </div>
          </div>
          <div className="mono" style={{ border: "1.5px dashed var(--amber)", color: "var(--amber)", fontSize: 12.5, padding: "12px 14px", lineHeight: 1.7 }}>
            Sale saved with a contingency copy: nothing lost, registered with the
            Ministry of Revenue the moment you're back online.
          </div>
        </motion.div>

        <div>
          <div className="kicker-star" style={{ textAlign: "left" }}>*** OFFLINE-FIRST ***</div>
          <PrintReveal className="h2" style={{ margin: "0 0 14px" }}>Never miss a sale<br />when the <em>network drops.</em></PrintReveal>
          <p style={{ color: "var(--muted)", fontSize: 16.5, maxWidth: 520, marginBottom: 22 }}>
            Power cuts and dead zones are a fact of business in Ethiopia. Receipt keeps
            selling: every sale is issued, saved and queued on the device, then
            registered with the Ministry of Revenue automatically once you're back
            online. Your customer walks away with a receipt either way.
          </p>
          <div className="mono" style={{ fontSize: 13.5, lineHeight: 2.2 }}>
            {checks.map((c) => (
              <div key={c}><span style={{ color: "var(--green)", border: "1px solid var(--green)", padding: "0 4px", marginRight: 10, fontSize: 11 }}>✓</span>{c}</div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
