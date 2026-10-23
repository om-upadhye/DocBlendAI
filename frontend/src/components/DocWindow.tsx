import { FileText, Minus, Plus, X } from "lucide-react";
import { useEffect, useRef, useState, type PointerEvent } from "react";
import { reducedMotion } from "../hooks";
import type { PageSet } from "../types";
import { PageFigure } from "./Preview";

const ZOOM_STEPS = [50, 67, 80, 100, 125, 150, 200, 250];

/** Where the window opens: a page index, or the saved place of a minimized window. */
export interface WindowPlace { index?: number; scrollTop?: number; zoom?: number; label?: string }
export type Minimized = PageSet & Required<Pick<WindowPlace, "scrollTop" | "zoom" | "label">>;

/**
 * Floating document window: opens smoothly over the page, zooms, shows the page you're on, and can be
 * dragged by its title bar. ✕, Esc or a click outside shrink it into a chip in the corner.
 */
export function DocWindow({ set, at, onMinimize }: { set: PageSet; at: WindowPlace; onMinimize: (saved: Minimized) => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const body = useRef<HTMLDivElement>(null);
  const figures = useRef<(HTMLDivElement | null)[]>([]);
  const [zoom, setZoom] = useState(at.zoom ?? 100);
  const [label, setLabel] = useState(at.label ?? `${set.word} ${(at.index ?? 0) + 1} of ${set.pages.length}`);
  const [closing, setClosing] = useState(false);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const drag = useRef<{ px: number; py: number; x: number; y: number } | null>(null);
  const restoring = at.scrollTop !== undefined;

  useEffect(() => {
    const win = dialog.current!;
    if (!win.open) win.showModal();
    const b = body.current!;
    b.style.scrollBehavior = "auto";
    requestAnimationFrame(() => {
      if (at.scrollTop !== undefined) b.scrollTop = at.scrollTop;  // restored: the same place as before
      else if (at.index) figures.current[at.index]?.scrollIntoView({ block: "start" });
      b.style.scrollBehavior = "";
    });
    const seen = new IntersectionObserver((entries) => {  // live "Page n of N" while scrolling
      const top = entries.filter((e) => e.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (top) setLabel(`${set.word} ${figures.current.indexOf(top.target as HTMLDivElement) + 1} of ${set.pages.length}`);
    }, { root: b, threshold: [0.25, 0.5, 0.75] });
    figures.current.forEach((f) => f && seen.observe(f));
    const wheel = (e: WheelEvent) => {  // Ctrl + wheel zooms the pages, not the site
      if (!e.ctrlKey) return;
      e.preventDefault();
      step(e.deltaY < 0 ? 1 : -1);
    };
    b.addEventListener("wheel", wheel, { passive: false });
    return () => { seen.disconnect(); b.removeEventListener("wheel", wheel); };
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  function step(dir: number) {
    setZoom((z) => (dir > 0 ? ZOOM_STEPS.find((s) => s > z) : [...ZOOM_STEPS].reverse().find((s) => s < z)) ?? z);
  }

  const labelRef = useRef(label);
  labelRef.current = label;
  const zoomRef = useRef(zoom);
  zoomRef.current = zoom;

  function minimize() {
    if (closing) return;
    const saved: Minimized = { ...set, scrollTop: body.current?.scrollTop ?? 0, zoom: zoomRef.current, label: labelRef.current };
    const finish = () => { dialog.current?.close(); onMinimize(saved); };
    if (reducedMotion()) { finish(); return; }
    setClosing(true);
    setTimeout(finish, 220);
  }

  const down = (e: PointerEvent<HTMLDivElement>) => {
    if ((e.target as HTMLElement).closest("button") || matchMedia("(max-width: 920px)").matches) return;
    drag.current = { px: e.clientX, py: e.clientY, ...offset };
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const move = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (d) setOffset({ x: d.x + e.clientX - d.px, y: d.y + e.clientY - d.py });
  };

  return (
    <dialog ref={dialog} className={`docwin${closing ? " is-closing" : ""}${restoring ? " is-restoring" : ""}`} aria-labelledby="dw-title"
            style={{ translate: `${offset.x}px ${offset.y}px` }}
            onCancel={(e) => { e.preventDefault(); minimize(); }}
            onClick={(e) => { if (e.target === dialog.current) minimize(); }}
            onKeyDown={(e) => {
              if (e.key === "+" || e.key === "=") { e.preventDefault(); step(1); }
              if (e.key === "-") { e.preventDefault(); step(-1); }
            }}>
      <div className={`docwin__head${drag.current ? " is-dragging" : ""}`} onPointerDown={down} onPointerMove={move}
           onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }}
           onDoubleClick={(e) => { if (!(e.target as HTMLElement).closest("button")) setOffset({ x: 0, y: 0 }); }}>
        <FileText size={17} aria-hidden="true" className="docwin__icon" />
        <h3 id="dw-title">{set.name}</h3>
        <span className="mono docwin__page">{label}</span>
        <div className="tray tray--sm docwin__zoom" role="group" aria-label="Zoom">
          <button type="button" className="tray__opt" onClick={() => step(-1)} aria-label="Zoom out"><Minus size={15} /></button>
          <span className="mono docwin__pct">{zoom}%</span>
          <button type="button" className="tray__opt" onClick={() => step(1)} aria-label="Zoom in"><Plus size={15} /></button>
          <button type="button" className="tray__opt" onClick={() => setZoom(100)}>Fit</button>
        </div>
        <button type="button" className="knob knob--close" onClick={minimize} aria-label="Minimize" title="Minimize"><X size={17} /></button>
      </div>
      <div className="docwin__body" ref={body}>
        <div className="docwin__pages" style={{ ["--zoom" as string]: zoom }}>
          {set.pages.map((p, i) => (
            <div key={p.page} ref={(n) => { figures.current[i] = n; }} className="docwin__page-wrap">
              <PageFigure page={p} word={set.word} total={set.pages.length} name={set.name} />
            </div>
          ))}
        </div>
      </div>
    </dialog>
  );
}

/** The minimized window: a chip in the corner that opens it again where you left off. */
export function WindowChip({ saved, onOpen, onClose }: { saved: Minimized; onOpen: () => void; onClose: () => void }) {
  return (
    <div className="chip-dock" role="group" aria-label="Minimized document">
      <button type="button" className="chip-dock__open" onClick={onOpen} title="Open again">
        <FileText size={16} aria-hidden="true" />
        <span className="chip-dock__name">{saved.name}</span>
        <span className="mono chip-dock__page">{saved.label}</span>
      </button>
      <button type="button" className="knob knob--sm knob--close" onClick={onClose} aria-label="Close the document window"><X size={14} /></button>
    </div>
  );
}
