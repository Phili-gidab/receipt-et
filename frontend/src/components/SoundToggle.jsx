import { useState } from "react";
import { initSound, setSound } from "../lib/sound.js";

/** Tiny persistent sound opt-in, docked bottom-left. Off by default. */
export default function SoundToggle() {
  const [on, setOn] = useState(() => initSound());
  const flip = () => {
    setSound(!on);
    setOn(!on);
  };
  return (
    <button type="button" className="snd-btn mono" onClick={flip} aria-pressed={on}
            title={on ? "Mute interface sounds" : "Enable interface sounds"}>
      {on ? "♪ SOUND · ON" : "♪ SOUND · OFF"}
    </button>
  );
}
