import { motion } from "framer-motion";
import PrintReveal from "./PrintReveal.jsx";

const steps = [
  { n: "01", t: "Sell", d: "Ring up the sale on the web POS — phone, tablet or desktop. Amharic-friendly, keyboard-fast, cashier-simple." },
  { n: "02", t: "Sign", d: "Each invoice is canonically serialized and signed SHA512-RSA with an INSA-issued digital certificate. Keys never leave the server." },
  { n: "03", t: "Register", d: "Sent to MoR EIMS in real time. Sequence-chained per business — no invoice can be skipped, duplicated or forged." },
  { n: "04", t: "Verify", d: "MoR returns the IRN and a government-signed QR. Print thermal or A4; anyone can scan and verify the sale instantly." },
];

export default function HowItWorks() {
  return (
    <section id="how" className="section" style={{ background: "var(--bg-2)" }}>
      <div className="container">
        <div className="kicker">HOW IT WORKS <span className="dots" /> FOUR STEPS</div>
        <PrintReveal className="h2">From “thank you”<br />to <em>tax-office truth.</em></PrintReveal>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(240px,1fr))", gap: 18, marginTop: 44 }}>
          {steps.map((s, i) => (
            <motion.div key={s.n}
              initial={{ opacity: 0, y: 26 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true, margin: "-60px" }}
              transition={{ delay: i * 0.12, duration: 0.55, ease: "easeOut" }}
              style={{ border: "1.5px dashed var(--line)", background: "var(--paper)", color: "var(--paper-ink)", padding: "26px 22px" }}>
              <div className="mono" style={{ color: "var(--green)", fontWeight: 600, fontSize: 13, letterSpacing: ".2em" }}>{s.n}</div>
              <div style={{ fontWeight: 900, fontSize: 22, textTransform: "uppercase", margin: "10px 0 8px" }}>{s.t}</div>
              <p style={{ color: "var(--paper-muted)", fontSize: 14.5 }}>{s.d}</p>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}
