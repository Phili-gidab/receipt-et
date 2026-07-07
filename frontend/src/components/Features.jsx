import { motion } from "framer-motion";
import PrintReveal from "./PrintReveal.jsx";

const feats = [
  ["01", "TAKE ANY PAYMENT", "Cash, card, telebirr and mobile money, all recorded on the fiscal receipt.", "▤"],
  ["02", "SEE YOUR SALES", "Live dashboard, daily summaries and VAT reports so you know where the day stands.", "▥"],
  ["03", "ISSUE EVERY DOC TYPE", "Invoices, receipts, cancellations, credit & debit memos: the full MoR set.", "▦"],
  ["04", "MANAGE YOUR TEAM", "Add cashiers, assign roles, secure each till. Every receipt traceable to its till.", "◫"],
  ["05", "EVERY RECEIPT ON FILE", "Search, reprint or void any sale from a history that supports retention rules.", "▧"],
  ["06", "VAT & WITHHOLDING", "Automatic 15% VAT math on every line: computed, chained, reported.", "%"],
  ["07", "MULTIPLE BRANCHES", "Run more than one location and keep each branch's receipts organised.", "▨"],
  ["08", "PRINT OR SHARE", "80mm thermal, A4, or a shareable digital receipt. Your customer's choice.", "⎙"],
];

export default function Features() {
  return (
    <section id="features" className="section">
      <div className="container">
        <div className="kicker-star">*** ITEMISED ***</div>
        <PrintReveal className="h2" style={{ textAlign: "center" }}>A full point of sale,<br /><em>not just a receipt printer.</em></PrintReveal>
        <p style={{ textAlign: "center", color: "var(--muted)", marginBottom: 50 }}>
          Receipt runs your counter and keeps you compliant at the same time, on the
          phone, tablet or computer you already own.
        </p>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(340px,1fr))", gap: "6px 56px", maxWidth: 1000, margin: "0 auto" }}>
          {feats.map(([n, t, d, icon], i) => (
            <motion.div key={n}
              initial={{ opacity: 0, y: 14 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: "-30px" }} transition={{ delay: (i % 2) * 0.08, duration: 0.45 }}
              style={{ padding: "18px 0", borderBottom: "1.5px dashed var(--line)" }}>
              <div className="leader" style={{ fontSize: 14, letterSpacing: ".1em" }}>
                <span style={{ color: "var(--green)", fontWeight: 600 }}>{n}</span>
                <span style={{ fontWeight: 700 }}>{t}</span>
                <span className="dots" />
                <span style={{ color: "var(--green)" }}>{icon}</span>
              </div>
              <p style={{ color: "var(--muted)", fontSize: 14.5, marginTop: 8, fontFamily: "Archivo" }}>{d}</p>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}
