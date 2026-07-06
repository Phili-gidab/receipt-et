import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { APP } from "../config.js";

const links = [
  ["#demo", "Demo"],
  ["#how", "How it works"],
  ["#features", "Features"],
  ["#compliance", "Compliance"],
  ["#faq", "FAQ"],
];

export default function Nav() {
  const [solid, setSolid] = useState(false);
  const [open, setOpen] = useState(false);
  const [dark, setDark] = useState(() => {
    const q = new URLSearchParams(window.location.search).get("theme");
    if (q) return q === "dark";
    const saved = localStorage.getItem("theme");
    if (saved) return saved === "dark";
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  });
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
    localStorage.setItem("theme", dark ? "dark" : "light");
  }, [dark]);
  const toggleTheme = () => setDark((d) => !d);
  useEffect(() => {
    const on = () => setSolid(window.scrollY > 24);
    window.addEventListener("scroll", on, { passive: true });
    return () => window.removeEventListener("scroll", on);
  }, []);
  // menu is mobile-only; make sure it never lingers after a resize to desktop
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 881px)");
    const close = () => mq.matches && setOpen(false);
    mq.addEventListener("change", close);
    return () => mq.removeEventListener("change", close);
  }, []);

  return (
    <header
      style={{
        position: "fixed", top: 0, left: 0, right: 0, zIndex: 50,
        background: solid || open ? "color-mix(in srgb, var(--bg) 94%, transparent)" : "transparent",
        backdropFilter: solid || open ? "blur(10px)" : "none",
        borderBottom: solid || open ? "1px dashed var(--line)" : "1px dashed transparent",
        transition: "all .25s ease",
      }}
    >
      <div className="container" style={{ display: "flex", alignItems: "center", gap: 18, height: 70 }}>
        <a href="#top" style={{ display: "flex", alignItems: "baseline", gap: 10, marginRight: "auto" }}>
          <span style={{ fontWeight: 900, fontSize: 21, letterSpacing: "-0.03em" }}>
            Receipt<span style={{ color: "var(--green)" }}>.</span>
          </span>
          <span className="mono nav-tag" style={{ fontSize: 10.5, letterSpacing: ".18em", color: "var(--muted)", whiteSpace: "nowrap" }}>
            · FISCAL RECEIPTS · ETB
          </span>
        </a>

        <nav className="mono nav-links" style={{ display: "flex", gap: 22, fontSize: 12, letterSpacing: ".12em", textTransform: "uppercase" }}>
          {links.map(([href, label]) => (
            <a key={href} href={href} style={{ color: "var(--muted)", whiteSpace: "nowrap" }}
               onMouseEnter={(e) => (e.target.style.color = "var(--ink)")}
               onMouseLeave={(e) => (e.target.style.color = "var(--muted)")}>
              {label}
            </a>
          ))}
        </nav>

        <div className="nav-actions" style={{ display: "flex", alignItems: "center", gap: 18 }}>
          <button onClick={toggleTheme} className="mono" title="Toggle theme"
                  style={{ fontSize: 12, letterSpacing: ".1em", color: "var(--muted)", display: "inline-flex", alignItems: "center", gap: 6 }}>
            {dark ? "◐ DARK" : "◑ LIGHT"}
          </button>
          <a className="mono" href={`${APP}/login`} style={{ fontSize: 12, letterSpacing: ".1em", color: "var(--muted)", whiteSpace: "nowrap" }}>
            Sign in
          </a>
        </div>

        <a className="btn btn-solid nav-cta" href={`${APP}/signup`} style={{ padding: "11px 18px", fontSize: 12, whiteSpace: "nowrap" }}>
          Get started
        </a>

        <button
          className="mono nav-burger"
          aria-label={open ? "Close menu" : "Open menu"}
          aria-expanded={open}
          onClick={() => setOpen((o) => !o)}
          style={{ fontSize: 13, letterSpacing: ".14em", color: "var(--ink)", alignItems: "center", gap: 7, padding: "8px 0 8px 4px", whiteSpace: "nowrap" }}
        >
          {open ? "✕" : "≡"}<span className="burger-label"> MENU</span>
        </button>
      </div>

      {/* mobile receipt-style dropdown */}
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.28, ease: [0.3, 0.1, 0.4, 1] }}
            style={{ overflow: "hidden", borderTop: "1px dashed var(--line)" }}
          >
            <div className="container mono" style={{ padding: "6px 0 20px", display: "flex", flexDirection: "column" }}>
              {links.map(([href, label]) => (
                <a key={href} href={href} onClick={() => setOpen(false)}
                   style={{ display: "flex", alignItems: "baseline", padding: "14px 0", fontSize: 13, letterSpacing: ".14em", textTransform: "uppercase", color: "var(--ink)", borderBottom: "1px dashed var(--line)" }}>
                  <span>{label}</span>
                  <span style={{ flex: 1, borderBottom: "2px dotted var(--line)", margin: "0 12px", transform: "translateY(-3px)" }} />
                  <span style={{ color: "var(--green)" }}>→</span>
                </a>
              ))}
              <div style={{ display: "flex", alignItems: "center", gap: 16, paddingTop: 18 }}>
                <button onClick={toggleTheme} className="mono"
                        style={{ fontSize: 12, letterSpacing: ".1em", color: "var(--muted)", display: "inline-flex", alignItems: "center", gap: 6 }}>
                  {dark ? "◐ DARK" : "◑ LIGHT"}
                </button>
                <a className="mono" href={`${APP}/login`} onClick={() => setOpen(false)}
                   style={{ fontSize: 12, letterSpacing: ".1em", color: "var(--muted)" }}>
                  Sign in
                </a>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </header>
  );
}
