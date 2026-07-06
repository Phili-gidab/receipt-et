import { APP } from "../config.js";
const tally = [
  ["SETUP TIME", "minutes"],
  ["HARDWARE REQUIRED", "none"],
  ["PAPERWORK", "none"],
];

const cols = {
  PRODUCT: [["#compliance", "Compliance"], ["#features", "Features"], ["#pricing", "Pricing"], ["#offline", "Offline mode"], ["#demo", "Live demo"]],
  COMPANY: [["#cta", "About"], ["mailto:hello@receipt.com.et", "Contact"], ["#faq", "Support"]],
  LEGAL: [["#", "Privacy Policy"], ["#", "Terms of Service"], ["#", "Security"]],
};

export default function Footer() {
  return (
    <>
      {/* receipt-style final CTA */}
      <section id="cta" className="section">
        <div className="container" style={{ maxWidth: 900 }}>
          <div style={{ background: "var(--bezel)", color: "#e9efe9", padding: "clamp(30px,5vw,64px)" }}>
            {tally.map(([k, v]) => (
              <div key={k} className="leader" style={{ padding: "7px 0", fontSize: 13.5, letterSpacing: ".14em", color: "#9aa79d" }}>
                <span>{k}</span>
                <span className="dots" style={{ borderColor: "#2a332c" }} />
                <span style={{ color: "#e9efe9" }}>{v}</span>
              </div>
            ))}
            <div style={{ borderTop: "1.5px dashed #2a332c", margin: "22px 0 30px" }} />
            <h2 style={{ fontWeight: 900, textTransform: "uppercase", textAlign: "center", letterSpacing: "-0.02em", lineHeight: 1.04, fontSize: "clamp(30px,4.8vw,56px)", marginBottom: 16 }}>
              Ready to sell<br /><span style={{ color: "#39d98a" }}>compliantly?</span>
            </h2>
            <p style={{ textAlign: "center", color: "#9aa79d", maxWidth: 520, margin: "0 auto 28px", fontSize: 15.5 }}>
              Join the pilot — we set you up, register your certificate, and your first
              government-verified receipt prints the same week.
            </p>
            <div style={{ display: "flex", gap: 14, justifyContent: "center", flexWrap: "wrap" }}>
              <a className="btn btn-solid" href={`${APP}/signup`} style={{ background: "#10b981", color: "#04140d" }}>Get started free</a>
              <a className="btn" href="#pricing" style={{ border: "1.5px dashed #3a453c", color: "#c9d3ca" }}>View pricing</a>
            </div>
          </div>
          <div className="cut" style={{ paddingBottom: 0 }}><span className="scissors">✂</span><span style={{ marginLeft: "auto" }}>TEAR HERE</span></div>
        </div>
      </section>

      {/* footer */}
      <footer style={{ borderTop: "1px dashed var(--line)", padding: "44px 0 34px" }}>
        <div className="container">
          <div style={{ display: "grid", gridTemplateColumns: "1.2fr repeat(3,.8fr)", gap: 28 }}>
            <div>
              <div style={{ fontWeight: 900, fontSize: 20 }}>Receipt<span style={{ color: "var(--green)" }}>.</span></div>
              <p className="mono" style={{ fontSize: 12, color: "var(--muted)", marginTop: 10, lineHeight: 1.8, maxWidth: 280 }}>
                Point of sale for Ethiopian businesses. Compliant fiscal receipts on
                every sale — online or offline.
              </p>
            </div>
            {Object.entries(cols).map(([h, links]) => (
              <div key={h}>
                <div className="mono" style={{ fontSize: 11.5, letterSpacing: ".18em", color: "var(--muted)", marginBottom: 12 }}>{h}</div>
                {links.map(([href, label]) => (
                  <a key={label} href={href} style={{ display: "block", fontSize: 14.5, padding: "4px 0", color: "var(--ink)" }}>{label}</a>
                ))}
              </div>
            ))}
          </div>
          <div className="mono" style={{ textAlign: "center", marginTop: 40, fontSize: 11.5, letterSpacing: ".18em", color: "var(--muted)" }}>
            *** THANK YOU · COME AGAIN ***
          </div>
          <div className="barcode" style={{ marginTop: 14 }} />
          <div className="mono" style={{ textAlign: "center", marginTop: 14, fontSize: 11, color: "var(--muted)" }}>
            © 2026 Receipt · Built for Ethiopian businesses · Made in Addis Ababa 🇪🇹
          </div>
        </div>
      </footer>
    </>
  );
}
