import { useEffect, useRef } from "react";
import { useInView, useMotionValue, useSpring } from "framer-motion";

function Counter({ to, suffix = "", decimals = 0 }) {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-80px" });
  const mv = useMotionValue(0);
  const spring = useSpring(mv, { duration: 1.6, bounce: 0 });
  useEffect(() => { if (inView) mv.set(to); }, [inView, to, mv]);
  useEffect(() =>
    spring.on("change", (v) => {
      if (ref.current) ref.current.textContent = v.toFixed(decimals) + suffix;
    }), [spring, suffix, decimals]);
  return <span ref={ref}>0{suffix}</span>;
}

const stats = [
  { big: <Counter to={2} suffix="s" />, label: "from sale to government-registered receipt" },
  { big: <Counter to={100} suffix="%" />, label: "MoR-compliant: VAT math, sequence chain, signed QR" },
  { big: <Counter to={39} />, label: "fiscal documents already chained in the MoR sandbox" },
  { big: <Counter to={0} />, label: "hardware to buy: works with the printer you have" },
];

export default function Stats() {
  return (
    <section className="section" style={{ borderTop: "none" }}>
      <div className="container" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))", gap: 0 }}>
        {stats.map((s, i) => (
          <div key={i} style={{ padding: "10px 28px", borderLeft: i ? "1px dashed var(--line)" : "none" }}>
            <div style={{ fontWeight: 900, fontSize: "clamp(40px,5vw,64px)", letterSpacing: "-0.03em", color: i === 1 ? "var(--green)" : "var(--ink)" }}>
              {s.big}
            </div>
            <div className="mono" style={{ fontSize: 12, color: "var(--muted)", lineHeight: 1.6, marginTop: 6 }}>{s.label}</div>
          </div>
        ))}
      </div>
    </section>
  );
}
