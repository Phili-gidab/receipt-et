import { motion, useReducedMotion } from "framer-motion";

/**
 * Reveals its children the way a thermal printer would: a glowing print-head
 * bar sweeps top→bottom and the text appears behind it. Fires once, when the
 * heading scrolls into view. Accepts arbitrary heading markup (<em>, <br/>).
 */
export default function PrintReveal({ as = "h2", className, style, children, delay = 0 }) {
  const reduced = useReducedMotion();
  if (reduced) {
    const Plain = as;
    return <Plain className={className} style={style}>{children}</Plain>;
  }
  const Tag = motion[as] || motion.div;
  const ease = [0.3, 0.1, 0.4, 1];
  const dur = 0.75;
  return (
    <div style={{ position: "relative" }}>
      <Tag
        className={className}
        style={style}
        initial={{ clipPath: "inset(0 0 100% 0)" }}
        whileInView={{ clipPath: "inset(0 0 -8% 0)" }}
        viewport={{ once: true, margin: "-70px" }}
        transition={{ delay, duration: dur, ease }}
      >
        {children}
      </Tag>
      <motion.div
        aria-hidden
        initial={{ top: "0%", opacity: 1 }}
        whileInView={{ top: "104%", opacity: 0 }}
        viewport={{ once: true, margin: "-70px" }}
        transition={{
          top: { delay, duration: dur, ease },
          opacity: { delay: delay + dur - 0.12, duration: 0.25 },
        }}
        style={{ position: "absolute", left: "4%", right: "4%", height: 2, background: "var(--green)", boxShadow: "0 0 14px var(--green)", pointerEvents: "none" }}
      />
    </div>
  );
}
