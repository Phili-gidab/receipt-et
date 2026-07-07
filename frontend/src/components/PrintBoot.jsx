import { useLayoutEffect, useRef, useState } from "react";
import gsap from "gsap";

/**
 * First-load "the page is printing" boot: a paper-colored shutter with a
 * zigzag tear edge and a glowing print-head line slides up, revealing the
 * page top-to-bottom like a receipt feeding out of a thermal printer.
 * Runs once per session; skipped for reduced motion and headless probes.
 */
export default function PrintBoot() {
  const ov = useRef(null);
  const pct = useRef(null);
  const [gone, setGone] = useState(false);

  useLayoutEffect(() => {
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const skip =
      reduced ||
      sessionStorage.getItem("receipt-booted") === "1" ||
      window.location.search.includes("goto=");
    if (skip) { setGone(true); return; }
    sessionStorage.setItem("receipt-booted", "1");
    document.documentElement.classList.add("booting");
    const tl = gsap.timeline({
      onComplete() {
        document.documentElement.classList.remove("booting");
        setGone(true);
      },
    });
    /* the cover slides DOWN so the page is revealed top-first — like paper
       feeding out of a printer head at the top of the screen */
    tl.to(ov.current, {
      yPercent: 104, duration: 1.05, ease: "power3.inOut", delay: 0.4,
      onUpdate() {
        if (pct.current) pct.current.textContent = Math.round(this.progress() * 100);
      },
    });
    return () => {
      document.documentElement.classList.remove("booting");
      tl.kill();
    };
  }, []);

  if (gone) return null;
  return (
    <div ref={ov} className="boot" aria-hidden="true">
      <div className="boot-rail boot-rail-l" />
      <div className="boot-rail boot-rail-r" />
      <div className="boot-brand">
        <span className="boot-logo">Receipt<span className="boot-dot">.</span></span>
        <span className="boot-domain mono">RECEIPT.COM.ET · 80MM · FEED</span>
        <span className="boot-status mono">PRINTING PAGE · <span ref={pct}>0</span>% <span className="cursor-blink">▮</span></span>
      </div>
      <div className="boot-line" />
      <div className="boot-teeth" />
    </div>
  );
}
