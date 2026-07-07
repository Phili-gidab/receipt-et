import { useEffect, useRef } from "react";
import gsap from "gsap";
import { tick } from "../lib/sound.js";

/**
 * Custom stamp cursor — desktop / fine pointers only.
 * A green dot marks the exact point; a lagging ring trails it. Over anything
 * interactive the ring blooms into a dashed "stamp" with a ✓; every click
 * leaves a brief ink ghost where you pressed. Hidden entirely on touch
 * devices and for reduced-motion users.
 */
const HOT = 'a,button,[role="button"],input,select,textarea,label,summary,.hf-card';

export default function Cursor() {
  const dot = useRef(null);
  const ring = useRef(null);
  const layer = useRef(null);

  useEffect(() => {
    const fine = window.matchMedia("(pointer: fine)").matches;
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (!fine || reduced) return;
    document.documentElement.classList.add("has-cursor");

    const dx = gsap.quickTo(dot.current, "x", { duration: 0.07, ease: "power2.out" });
    const dy = gsap.quickTo(dot.current, "y", { duration: 0.07, ease: "power2.out" });
    const rx = gsap.quickTo(ring.current, "x", { duration: 0.26, ease: "power3.out" });
    const ry = gsap.quickTo(ring.current, "y", { duration: 0.26, ease: "power3.out" });

    let seen = false;
    const move = (e) => {
      if (!seen) {
        seen = true;
        gsap.set([dot.current, ring.current], { x: e.clientX, y: e.clientY, autoAlpha: 1 });
      }
      dx(e.clientX); dy(e.clientY); rx(e.clientX); ry(e.clientY);
    };
    const over = (e) => {
      const hot = e.target.closest?.(HOT);
      ring.current.classList.toggle("is-hot", !!hot);
    };
    const down = () => ring.current.classList.add("is-press");
    const up = () => ring.current.classList.remove("is-press");
    const click = (e) => {
      tick(0.8);
      const ink = document.createElement("span");
      ink.className = "cur-ink";
      ink.style.left = e.clientX + "px";
      ink.style.top = e.clientY + "px";
      layer.current?.appendChild(ink);
      setTimeout(() => ink.remove(), 750);
    };
    const leave = (e) => {
      if (!e.relatedTarget) gsap.to([dot.current, ring.current], { autoAlpha: 0, duration: 0.2 });
    };
    const enter = () => {
      if (seen) gsap.to([dot.current, ring.current], { autoAlpha: 1, duration: 0.2 });
    };

    window.addEventListener("mousemove", move, { passive: true });
    document.addEventListener("mouseover", over, { passive: true });
    document.addEventListener("mousedown", down, { passive: true });
    document.addEventListener("mouseup", up, { passive: true });
    document.addEventListener("click", click, { passive: true });
    document.addEventListener("mouseout", leave, { passive: true });
    document.addEventListener("mouseenter", enter, { passive: true });
    return () => {
      document.documentElement.classList.remove("has-cursor");
      window.removeEventListener("mousemove", move);
      document.removeEventListener("mouseover", over);
      document.removeEventListener("mousedown", down);
      document.removeEventListener("mouseup", up);
      document.removeEventListener("click", click);
      document.removeEventListener("mouseout", leave);
      document.removeEventListener("mouseenter", enter);
    };
  }, []);

  return (
    <>
      <div ref={dot} className="cur-dot" aria-hidden="true" />
      <div ref={ring} className="cur-ring" aria-hidden="true"><span className="cur-ring-in" /></div>
      <div ref={layer} className="cur-layer" aria-hidden="true" />
    </>
  );
}
