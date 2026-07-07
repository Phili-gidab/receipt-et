import { useEffect, useLayoutEffect, useRef } from "react";
import Lenis from "lenis";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

import Nav from "./components/Nav.jsx";
import Hero from "./components/Hero.jsx";
import Marquee from "./components/Marquee.jsx";
import Tally from "./components/Tally.jsx";
import Offline from "./components/Offline.jsx";
import Pricing from "./components/Pricing.jsx";
import LiveDemo from "./components/LiveDemo.jsx";
import HowItWorks from "./components/HowItWorks.jsx";
import Features from "./components/Features.jsx";
import Compliance from "./components/Compliance.jsx";
import FAQ from "./components/FAQ.jsx";
import Footer from "./components/Footer.jsx";
import Cursor from "./components/Cursor.jsx";
import PrintBoot from "./components/PrintBoot.jsx";
import SoundToggle from "./components/SoundToggle.jsx";

gsap.registerPlugin(ScrollTrigger);

/* ✂ travels along the perforation as the divider crosses the viewport,
   and the paper visibly separates behind the blade: left of the scissors
   the line is torn into two offset edges, right of it still intact. */
function Cut() {
  const row = useRef(null);
  useLayoutEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const ctx = gsap.context(() => {
      const el = row.current;
      const blade = el.querySelector(".scissors");
      const uncut = el.querySelector(".cut-uncut");
      const top = el.querySelector(".cut-top");
      const bot = el.querySelector(".cut-bot");
      ScrollTrigger.create({
        trigger: el,
        start: "top 92%",
        end: "top 26%",
        scrub: 0.5,
        onUpdate(self) {
          const w = el.offsetWidth;
          const x = self.progress * (w - 30);
          gsap.set(blade, { x });
          const cutPx = Math.max(0, x + 8);
          /* torn halves visible only left of the blade; intact line right of it */
          const torn = `inset(-10px ${Math.max(0, w - cutPx)}px -10px 0)`;
          uncut.style.clipPath = `inset(-10px 0 -10px ${cutPx}px)`;
          top.style.clipPath = torn;
          bot.style.clipPath = torn;
        },
      });
    }, row);
    return () => ctx.revert();
  }, []);
  return (
    <div className="container">
      <div className="cut2" ref={row} aria-hidden="true">
        <span className="cut-uncut" />
        <span className="cut-top" />
        <span className="cut-bot" />
        <span className="scissors">✂</span>
      </div>
    </div>
  );
}

/* thermal paper-feed scroll progress — a thin strip of receipt paper
   "prints out" under the nav as you move down the roll. */
function FeedProgress() {
  const bar = useRef(null);
  useLayoutEffect(() => {
    const st = ScrollTrigger.create({
      start: 0,
      end: "max",
      onUpdate: (self) => {
        if (bar.current) bar.current.style.transform = `scaleX(${self.progress})`;
      },
    });
    return () => st.kill();
  }, []);
  return (
    <div className="feedbar" aria-hidden="true">
      <div className="feedbar-fill" ref={bar} />
    </div>
  );
}

export default function App() {
  useEffect(() => {
    // dev helper: ?goto=<section-id> scrolls after load (headless screenshots)
    const g = new URLSearchParams(window.location.search).get("goto");
    if (g) setTimeout(() => document.getElementById(g)?.scrollIntoView({ behavior: "instant", block: "start" }), 700);
  }, []);
  useEffect(() => {
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced) return;
    const lenis = new Lenis({ lerp: 0.11, smoothWheel: true });
    lenis.on("scroll", ScrollTrigger.update);
    const raf = (t) => lenis.raf(t * 1000);
    gsap.ticker.add(raf);
    gsap.ticker.lagSmoothing(0);
    // route in-page anchors through Lenis so nav clicks glide instead of jumping
    const onAnchor = (e) => {
      const a = e.target.closest?.('a[href^="#"]');
      if (!a) return;
      const el = document.querySelector(a.getAttribute("href"));
      if (!el) return;
      e.preventDefault();
      lenis.scrollTo(el, { offset: -70, duration: 1.15 });
    };
    document.addEventListener("click", onAnchor);
    // ink smear: headlines lean with scroll velocity, marquee shears sideways
    const smears = gsap.utils.toArray(".h2").map((el) =>
      gsap.quickTo(el, "skewY", { duration: 0.5, ease: "power3.out" })
    );
    const mq = document.querySelector(".marquee-smear");
    const mSet = mq ? gsap.quickTo(mq, "skewX", { duration: 0.5, ease: "power3.out" }) : null;
    const onVel = (e) => {
      const v = e.velocity || 0;
      const s = gsap.utils.clamp(-2, 2, v * 0.03);
      smears.forEach((f) => f(s));
      mSet?.(gsap.utils.clamp(-6, 6, v * 0.09));
    };
    lenis.on("scroll", onVel);
    return () => {
      document.removeEventListener("click", onAnchor);
      gsap.ticker.remove(raf);
      lenis.destroy();
    };
  }, []);

  return (
    <>
      <PrintBoot />
      <Cursor />
      <SoundToggle />
      <Nav />
      <FeedProgress />
      <div className="frame">
        <Hero />
        <Marquee />
        <Tally />
        <Cut />
        <Compliance />
        <LiveDemo />
        <Cut />
        <Offline />
        <Features />
        <Cut />
        <HowItWorks />
        <Pricing />
        <FAQ />
        <Footer />
      </div>
    </>
  );
}
