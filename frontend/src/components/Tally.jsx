/** Receipt-style compliance tally — leader dots, totalled like a bill. */
const rows = [
  ["QR ON EVERY RECEIPT", "as MoR requires", false],
  ["WORKS OFFLINE", "100%", false],
  ["VAT COMPUTED FOR YOU", "15%", false],
  ["EXTRA FISCAL MACHINES", "0", false],
];

export default function Tally() {
  return (
    <section style={{ padding: "clamp(40px,6vw,72px) 0" }}>
      <div className="container" style={{ maxWidth: 760 }}>
        {rows.map(([k, v]) => (
          <div key={k} className="leader" style={{ padding: "9px 0", fontSize: 14.5, letterSpacing: ".08em" }}>
            <span style={{ fontWeight: 600 }}>{k}</span>
            <span className="dots" />
            <span style={{ color: "var(--green)", fontWeight: 600 }}>{v}</span>
          </div>
        ))}
        <div className="leader" style={{ padding: "14px 0 0", fontSize: 17, letterSpacing: ".08em", borderTop: "2px solid var(--ink)", marginTop: 10 }}>
          <span style={{ fontWeight: 700 }}>TOTAL</span>
          <span className="dots" />
          <span style={{ color: "var(--green)", fontWeight: 700 }}>Compliance ✓</span>
        </div>
      </div>
    </section>
  );
}
