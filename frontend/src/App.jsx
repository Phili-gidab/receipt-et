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

gsap.registerPlugin(ScrollTrigger);

/* ✂ travels along the perforation as the divider crosses the viewport —
   scroll literally cuts the page into slips. */
function Cut() {
  const row = useRef(null);
  const blade = useRef(null);
  useLayoutEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const ctx = gsap.context(() => {
      gsap.fromTo(blade.current, { x: 0 }, {
        x: () => row.current.offsetWidth - 34,
        ease: "none",
        scrollTrigger: { trigger: row.current, start: "top 92%", end: "top 30%", scrub: 0.6 },
      });
    }, row);
    return () => ctx.revert();
  }, []);
  return (
    <div className="container">
      <div className="cut" ref={row}><span className="scissors" ref={blade}>✂</span></div>
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
    return () => {
      document.removeEventListener("click", onAnchor);
      gsap.ticker.remove(raf);
      lenis.destroy();
    };
  }, []);

  return (
    <>
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
