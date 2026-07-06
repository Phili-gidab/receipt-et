const items = [
  "MoR EIMS · REAL-TIME REGISTRATION",
  "INSA-SIGNED · SHA512-RSA",
  "SIGNED QR ON EVERY RECEIPT",
  "VAT 15 · B2C · B2B · B2G",
  "CREDIT & DEBIT MEMOS",
  "SEQUENCE-CHAINED · TAMPER-PROOF",
  "ANY PRINTER · THERMAL OR A4",
];

export default function Marquee() {
  const row = [...items, ...items];
  return (
    <div style={{ borderTop: "1px dashed var(--line)", borderBottom: "1px dashed var(--line)", overflow: "hidden", padding: "13px 0", background: "var(--bg-2)" }}>
      <div className="mono marquee-track" style={{ display: "flex", gap: 44, whiteSpace: "nowrap", fontSize: 12, letterSpacing: ".16em", color: "var(--muted)", animation: "scrollX 36s linear infinite", width: "max-content" }}>
        {row.map((t, i) => (
          <span key={i}>
            <span style={{ color: "var(--green)", marginRight: 10 }}>▮</span>{t}
          </span>
        ))}
      </div>
      <style>{`@keyframes scrollX { from { transform: translateX(0) } to { transform: translateX(-50%) } }`}</style>
    </div>
  );
}
