import { useEffect, useRef, useState } from "react";

// Realistic talking avatar: base portrait + pixel-aligned layers (mouth shapes, blink, arm gestures)
// from /public/avatar (built by backend/scripts/avatar). The mouth follows the text as it is revealed.

interface Layer { src: string; box: [number, number, number, number] }
interface Manifest { width: number; height: number; view?: [number, number, number, number]; patches: Record<string, Layer>; gestures?: Record<string, Layer> }

const VOWEL: Record<string, string> = { a: "talk.aa", e: "talk.ee", i: "talk.ee", y: "talk.ee", o: "talk.oh", u: "talk.ou", w: "talk.ou" };
const CPS = 38, HOLD = 80;
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const pct = (v: number, of: number) => `${(v / of) * 100}%`;

export default function Assistant({ message }: { message: { id: number; text: string } | null }) {
  const [man, setMan] = useState<Manifest | null>(null);
  const [shown, setShown] = useState("");
  const [speaking, setSpeaking] = useState(false);
  const [mouth, setMouth] = useState<string | null>(null);
  const [gesture, setGesture] = useState<string | null>(null);
  const [blinkKey, setBlinkKey] = useState(0);
  const queue = useRef<Promise<void>>(Promise.resolve());
  const lastGesture = useRef<string | null>(null);

  useEffect(() => { fetch("/avatar/manifest.json").then((r) => r.json()).then(setMan).catch(() => setMan(null)); }, []);

  useEffect(() => {  // blink: the length is a CSS animation, restarted every few seconds
    let t: ReturnType<typeof setTimeout>;
    const loop = () => { t = setTimeout(() => { setBlinkKey((k) => k + 1); loop(); }, 2500 + Math.random() * 3500); };
    loop();
    return () => clearTimeout(t);
  }, []);

  useEffect(() => {
    if (!message) return;
    const text = message.text;
    queue.current = queue.current.then(() => speak(text));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [message?.id]);

  function pickGesture(sentence: string): string | null {
    const names = Object.keys(man?.gestures || {});
    if (!names.length) return null;
    const t = sentence.toLowerCase();
    let pick = /\?|which|what|need|confirm/.test(t) ? "crossed" : /\$|price|quote|ready|total/.test(t) ? "present" : null;
    if (!pick || !names.includes(pick) || pick === lastGesture.current) {
      const pool = names.filter((n) => n !== lastGesture.current);
      pick = pool[Math.floor(Math.random() * pool.length)];
    }
    lastGesture.current = pick;
    return pick;
  }

  async function speak(text: string) {
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) { setShown(text); return; }
    setSpeaking(true);
    setShown("");
    const sentences = text.match(/[^.!?]+[.!?]*/g) || [text];
    let sIdx = 0, sEnd = sentences[0].length, last = 0, lastG = performance.now();
    setGesture(pickGesture(sentences[0]));
    let out = "";
    for (let i = 0; i < text.length; i++) {
      const ch = text[i], lc = ch.toLowerCase(), now = performance.now();
      out += ch;
      setShown(out);
      if (i >= sEnd && sIdx < sentences.length - 1) {
        sIdx++; sEnd += sentences[sIdx].length;
        if (now - lastG > 1800) { setGesture(pickGesture(sentences[sIdx])); lastG = now; }
      }
      if (/[.!?:]/.test(ch)) { setMouth(null); await sleep(260); continue; }
      if (/[,;\n]/.test(ch)) { setMouth(null); await sleep(140); continue; }
      if (now - last > HOLD) { setMouth(ch === " " ? null : VOWEL[lc] || (/[a-z0-9$]/.test(lc) ? "talk.half" : null)); last = now; }
      await sleep(1000 / CPS);
    }
    setMouth(null);
    await sleep(500);
    setGesture(null);
    setSpeaking(false);
  }

  const view = man?.view || [0, 0, man?.width || 1, man?.height || 1];
  const vw = view[2] - view[0], vh = view[3] - view[1];
  const layer = (name: string, l: Layer, cls: string, on: boolean, key?: number) => (
    <img key={key !== undefined ? `${name}-${key}` : name} src={`/avatar/${l.src}`} alt="" className={`${cls}${on ? " on" : ""}`}
      style={{ left: pct(l.box[0], man!.width), top: pct(l.box[1], man!.height), width: pct(l.box[2] - l.box[0], man!.width), height: pct(l.box[3] - l.box[1], man!.height) }} />
  );

  return (
    <div className="assistant-card">
      <div className="assistant-portrait" style={{ aspectRatio: `${vw} / ${vh}` }}>
        {man && (
          <div className="assistant-stage" style={{ width: pct(man.width, vw), height: pct(man.height, vw), left: pct(-view[0], vw), top: pct(-view[1], vw) }}>
            <img src="/avatar/base.webp" alt="" style={{ left: 0, top: 0, width: "100%", height: "100%" }} />
            {Object.entries(man.gestures || {}).map(([n, l]) => layer(n, l, "assistant-gesture", gesture === n))}
            {Object.entries(man.patches).filter(([n]) => n !== "blink").map(([n, l]) => layer(n, l, "assistant-patch", mouth === n))}
            {man.patches.blink && layer("blink", man.patches.blink, "assistant-patch assistant-blink", false, blinkKey)}
          </div>
        )}
        <span className="assistant-tag">AI avatar</span>
      </div>
      <div className="assistant-talk">
        <div className="assistant-name"><strong>Quote assistant</strong><span className={speaking ? "speaking" : ""}>{speaking ? "speaking" : "listening"}</span></div>
        <p aria-live="polite">{shown || "Paste an RFQ or drop a file. I'll match each line to the catalog, price it, check compliance, and ask about anything unclear."}</p>
      </div>
    </div>
  );
}
