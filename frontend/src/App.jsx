import { useEffect } from "react";
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

function Cut() {
  return (
    <div className="container">
      <div className="cut"><span className="scissors">✂</span></div>
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
    return () => {
      gsap.ticker.remove(raf);
      lenis.destroy();
    };
  }, []);

  return (
    <>
      <Nav />
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
