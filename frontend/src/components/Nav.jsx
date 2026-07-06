import { useEffect, useState } from "react";
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

  return (
    <header
      style={{
        position: "fixed", top: 0, left: 0, right: 0, zIndex: 50,
        background: solid ? "color-mix(in srgb, var(--bg) 92%, transparent)" : "transparent",
        backdropFilter: solid ? "blur(10px)" : "none",
        borderBottom: solid ? "1px dashed var(--line)" : "1px dashed transparent",
        transition: "all .25s ease",
      }}
    >
      <div className="container" style={{ display: "flex", alignItems: "center", gap: 26, height: 70 }}>
        <a href="#top" style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
          <span style={{ fontWeight: 900, fontSize: 21, letterSpacing: "-0.03em" }}>
            Receipt<span style={{ color: "var(--green)" }}>.</span>
          </span>
          <span className="mono" style={{ fontSize: 10.5, letterSpacing: ".18em", color: "var(--muted)" }}>
            · FISCAL RECEIPTS · ETB
          </span>
        </a>
        <nav className="mono" style={{ display: "flex", gap: 22, marginLeft: "auto", fontSize: 12, letterSpacing: ".12em", textTransform: "uppercase" }}>
          {links.map(([href, label]) => (
            <a key={href} href={href} style={{ color: "var(--muted)" }}
               onMouseEnter={(e) => (e.target.style.color = "var(--ink)")}
               onMouseLeave={(e) => (e.target.style.color = "var(--muted)")}>
              {label}
            </a>
          ))}
        </nav>
        <button onClick={toggleTheme} className="mono" title="Toggle theme"
                style={{ fontSize: 12, letterSpacing: ".1em", color: "var(--muted)", display: "inline-flex", alignItems: "center", gap: 6 }}>
          {dark ? "◐ DARK" : "◑ LIGHT"}
        </button>
        <a className="mono" href={`${APP}/login`} style={{ fontSize: 12, letterSpacing: ".1em", color: "var(--muted)" }}>
          Sign in
        </a>
        <a className="btn btn-solid" href={`${APP}/signup`} style={{ padding: "11px 20px", fontSize: 12 }}>
          Get started
        </a>
      </div>
    </header>
  );
}
