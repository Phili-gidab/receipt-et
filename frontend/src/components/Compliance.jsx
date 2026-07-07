import { motion } from "framer-motion";
import { RECEIPT } from "../data/receipt.js";
import PrintReveal from "./PrintReveal.jsx";

const cards = [
  { stamp: "Directive 188", t: "A valid QR on every receipt", d: "Every tax invoice must carry a unique, tax-authority-validated QR code. Receipt prints one on every sale, with no separate fiscal machine to babysit." },
  { stamp: "Verified", t: "Verifiable by anyone", d: "Buyers can scan and confirm a receipt's authenticity through the Ministry of Revenue's verification service. Real receipts, real records." },
  { stamp: "No penalties", t: "Avoid “illegal receipt” fines", d: "The MoR is phasing out manual paper receipts; non-QR receipts can be rejected for VAT deduction. Receipt keeps every sale on the right side of the rules." },
  { stamp: "VAT 15%", t: "Correct tax, every time", d: "Ethiopia's 15% VAT computed on every line, sequence-chained and signed, captured on the invoice and ready for reporting." },
];

export default function Compliance() {
  return (
    <section id="compliance" className="section" style={{ background: "var(--bg-2)" }}>
      <div className="container">
        <div className="kicker-star">*** COMPLIANCE, HANDLED ***</div>
        <PrintReveal className="h2" style={{ textAlign: "center" }}>Running a shop is hard.<br /><em>Staying tax-compliant shouldn't be.</em></PrintReveal>
        <p style={{ textAlign: "center", color: "var(--muted)", maxWidth: 620, margin: "0 auto 50px" }}>
          Ethiopia is moving from paper receipts to tax-validated, QR-coded invoices.
          Receipt keeps you compliant with the Ministry of Revenue's electronic
          invoicing, without changing how you sell.
        </p>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(300px,1fr))", gap: "26px 20px" }}>
          {cards.map((c, i) => (
            <motion.div key={c.stamp}
              initial={{ opacity: 0, y: 20 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: "-40px" }} transition={{ delay: (i % 2) * 0.1, duration: 0.5 }}
              style={{ position: "relative", border: "1.5px dashed var(--line)", padding: "30px 24px 24px", background: "var(--paper)", color: "var(--paper-ink)" }}>
              <span className="stamp">{c.stamp}</span>
              <div style={{ fontWeight: 800, fontSize: 18, textTransform: "uppercase", marginBottom: 8 }}>{c.t}</div>
              <p style={{ color: "var(--paper-muted)", fontSize: 14.5 }}>{c.d}</p>
            </motion.div>
          ))}
        </div>

        <div className="mono" style={{ border: "1.5px dashed var(--green-deep)", marginTop: 22, padding: "14px 18px", fontSize: 12, color: "var(--green-deep)", background: "var(--paper)", wordBreak: "break-all" }}>
          <b>EVIDENCE</b> · registered in the MoR sandbox by this platform · IRN {RECEIPT.irn} · RRN {RECEIPT.rrn}
        </div>
        <p className="mono" style={{ textAlign: "center", fontSize: 11, letterSpacing: ".12em", color: "var(--muted)", marginTop: 26, textTransform: "uppercase" }}>
          Receipt is designed to comply with the Ministry of Revenue's electronic invoicing
          requirements. It is an independent product and not a government service.
        </p>
      </div>
    </section>
  );
}
