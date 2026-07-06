import { motion } from "framer-motion";
import { APP } from "../config.js";
import PrintReveal from "./PrintReveal.jsx";

const plans = [
  {
    name: "STARTER", price: "Free", per: "for a single till", popular: false,
    items: ["QR fiscal receipts", "One location, one user", "Offline mode", "Cash & mobile-money payments", "Daily sales summary"],
    cta: "Start free",
  },
  {
    name: "BUSINESS", price: "ETB 500", per: "per month", popular: true,
    items: ["Everything in Starter", "Unlimited receipts", "Inventory & customers", "Staff accounts & PIN roles", "VAT & withholding reports", "Credit & debit memos"],
    cta: "Get started",
  },
  {
    name: "MULTI-BRANCH", price: "Let's talk", per: "for chains & franchises", popular: false,
    items: ["Everything in Business", "Multiple branches", "Consolidated reporting", "Priority support", "Onboarding assistance"],
    cta: "Contact us",
  },
];

export default function Pricing() {
  return (
    <section id="pricing" className="section">
      <div className="container">
        <div className="kicker-star">*** SIMPLE PRICING ***</div>
        <PrintReveal className="h2" style={{ textAlign: "center" }}>Transparent plans.<br /><em>No hidden fees.</em></PrintReveal>
        <p style={{ textAlign: "center", color: "var(--muted)", marginBottom: 46 }}>
          Start free and upgrade when you grow. Compliance is included on every plan.
        </p>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(270px,1fr))", gap: 20, alignItems: "stretch" }}>
          {plans.map((p, i) => (
            <motion.div key={p.name}
              initial={{ opacity: 0, y: 22 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: "-40px" }} transition={{ delay: i * 0.1, duration: 0.5 }}
              style={{
                position: "relative", padding: "34px 26px 26px", display: "flex", flexDirection: "column",
                border: p.popular ? "2px solid var(--green)" : "1.5px dashed var(--line)",
                background: "var(--paper)", color: "var(--paper-ink)",
                boxShadow: p.popular ? "6px 6px 0 var(--green-deep)" : "none",
              }}>
              {p.popular && <span className="stamp">Most popular</span>}
              <div className="mono" style={{ fontSize: 12, letterSpacing: ".2em", color: "var(--paper-muted)" }}>{p.name}</div>
              <div className="mono" style={{ fontSize: 40, fontWeight: 600, margin: "10px 0 2px" }}>{p.price}</div>
              <div style={{ color: "var(--paper-muted)", fontSize: 13.5, marginBottom: 18 }}>{p.per}</div>
              <div className="dash-rule" />
              <div className="mono" style={{ fontSize: 13, lineHeight: 2.1, flex: 1 }}>
                {p.items.map((it) => (
                  <div key={it}><span style={{ color: "var(--green)", marginRight: 9 }}>✓</span>{it}</div>
                ))}
              </div>
              <a className={p.popular ? "btn btn-solid" : "btn btn-ghost"} href={`${APP}/signup`}
                 style={{ justifyContent: "center", marginTop: 20, ...(p.popular ? {} : { color: "var(--paper-ink)", borderColor: "#b9b5a6" }) }}>
                {p.cta}
              </a>
              <div className="barcode" style={{ marginTop: 20 }} />
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
}
