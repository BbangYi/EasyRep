"use client";

import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import { ArrowRight } from "lucide-react";
import { BrandLogo } from "./brand-logo";

// The dashboard loads underneath; CSS owns the entrance clock, including before hydration.
const INTRO_DURATION_MS = 3200;
// Client-module lifetime equals this document. Route remounts must not replay it.
// Effects never run during SSR, so this flag is not shared between server requests.
let entranceClaimed = false;

export function useForestMotion(autoPlay = true) {
  const [playing, setPlaying] = useState(() => autoPlay && !entranceClaimed);
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    entranceClaimed = true;
    const preference = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => {
      setReduced(preference.matches);
      if (preference.matches) setPlaying(false);
    };
    sync();
    preference.addEventListener("change", sync);
    return () => preference.removeEventListener("change", sync);
  }, []);

  useEffect(() => {
    if (!playing || reduced) return;
    // Capture on window so keyboard use also bypasses the entrance from <body>.
    const stopForKeyboard = (event: KeyboardEvent) => {
      if (event.key === "Escape" || event.key === "Tab") setPlaying(false);
    };
    window.addEventListener("keydown", stopForKeyboard, true);
    return () => {
      window.removeEventListener("keydown", stopForKeyboard, true);
    };
  }, [playing, reduced]);

  const skip = useCallback(() => setPlaying(false), []);

  return {
    playing: playing && !reduced,
    reduced,
    skip,
    replay: () => { if (!reduced) setPlaying(true); },
  };
}

export function ForestEntrance({ onSkip }: { onSkip: () => void }) {
  const entranceRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // A CSS animation may already be finished when hydration reaches this component.
    // Its finished promise settles immediately in that case; never restart a 3.2s timer.
    const animation = entranceRef.current?.getAnimations().find(
      (item) => "animationName" in item && item.animationName === "forest-entrance-exit",
    );
    if (!animation) {
      onSkip();
      return;
    }
    let active = true;
    const finish = () => { if (active) onSkip(); };
    void animation.finished.then(finish, finish);
    return () => { active = false; };
  }, [onSkip]);

  return (
    <div ref={entranceRef} className="forest-entrance" style={{ "--intro-duration": `${INTRO_DURATION_MS}ms` } as CSSProperties}>
      <div className="forest-entrance-scene" aria-hidden="true" />
      <div className="forest-entrance-brand">
        <BrandLogo />
      </div>
      <button type="button" className="forest-entrance-skip" onClick={onSkip}>
        바로 보기 <ArrowRight size={16} aria-hidden="true" />
      </button>
    </div>
  );
}
