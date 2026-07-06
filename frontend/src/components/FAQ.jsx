import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import PrintReveal from "./PrintReveal.jsx";

const faqs = [
  ["Is this legal / approved by the Ministry of Revenue?",
   "Receipt integrates directly with MoR's EIMS platform and follows the e-invoicing directive: INSA-signed payloads, sequence-chained invoices, government-issued IRN and QR on every receipt. Certification evidence is being assembled with MoR now — the demo receipt on this page was registered in MoR's own sandbox."],
  ["Do I need special hardware?",
   "No. Receipt runs in a browser on any phone, tablet or computer, and prints to the thermal or A4 printer you already own."],
  ["What happens when the internet goes down?",
   "Sales continue. They queue locally and register with MoR automatically when the connection returns — with the sequence chain kept intact. (Offline PWA mode is in active development.)"],
  ["Can it talk to my existing software?",
   "Yes — the same fiscal engine is exposed as a clean REST API with OpenAPI docs, so ERPs, e-commerce stores and custom apps can register invoices through Receipt."],
  ["What does it cost?",
   "Simple monthly per-business pricing — no hardware, no per-receipt fees. Early pilot businesses get onboarding help and preferential terms; talk to us."],
];

export default function FAQ() {
  const [open, setOpen] = useState(0);
  return (
    <section id="faq" className="section">
      <div className="container" style={{ maxWidth: 860 }}>
        <div className="kicker">FAQ <span className="dots" /> STRAIGHT ANSWERS</div>
        <PrintReveal className="h2">Questions,<em> answered.</em></PrintReveal>
        <div style={{ marginTop: 34 }}>
          {faqs.map(([q, a], i) => (
            <div key={i} style={{ borderBottom: "1.5px dashed var(--line)" }}>
              <button onClick={() => setOpen(open === i ? -1 : i)}
                      style={{ width: "100%", textAlign: "left", padding: "20px 4px", display: "flex", justifyContent: "space-between", alignItems: "center", gap: 16 }}>
                <span style={{ fontWeight: 700, fontSize: 17, color: "var(--ink)" }}>{q}</span>
                <span className="mono" style={{ color: "var(--green)", fontSize: 20, flexShrink: 0 }}>{open === i ? "−" : "+"}</span>
              </button>
              <AnimatePresence initial={false}>
                {open === i && (
                  <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }}
                              transition={{ duration: 0.3, ease: "easeInOut" }} style={{ overflow: "hidden" }}>
                    <p style={{ color: "var(--muted)", fontSize: 15, padding: "0 4px 20px", maxWidth: 720 }}>{a}</p>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
