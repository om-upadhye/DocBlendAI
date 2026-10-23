import { ChevronLeft, ChevronRight, X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "../api";
import { useTouch } from "../hooks";
import type { Block, Doc, Page } from "../types";
import { BLOCK, CONF_WORD, FORMAT, REGION, confTone, plural } from "../words";
import { DownloadMenu } from "./DownloadMenu";
import { Knob, Push, Tray } from "./Keys";

type Mode = "layout" | "lines" | "spacing";
const parts_ = (n: number) => `${n} part${n === 1 ? "" : "s"}`;
const MODE_NAMES: Record<Mode, string> = { layout: "Layout", lines: "Lines", spacing: "Spacing" };

/** One outlined part of the page with its row in the side list; hovering either highlights both. */
interface Part { key: string; cls: string; box?: number[] | null; tip: string; row: ReactNode; card?: ReactNode }

function Cells({ rows }: { rows: string[][] }) {
  return (
    <div className="cells">
      <table><tbody>{rows.map((row, i) => <tr key={i}>{row.map((c, j) => <td key={j}>{c}</td>)}</tr>)}</tbody></table>
    </div>
  );
}

function blockSummary(b: Block): string {
  if (b.type === "table" && b.rows) {
    const cols = Math.max(0, ...b.rows.map((r) => r.length));
    return `${b.rows.length} rows × ${cols} columns: ${(b.rows[0] || []).join(" · ")}`;
  }
  if (b.type === "image") return b.text ? `Picture: ${b.text}` : "Picture";
  return b.text;
}

/** Word / PowerPoint / text files have no page image, so the page is rebuilt from its blocks. */
function blockCard(b: Block): ReactNode {
  if (b.type === "table" && b.rows) return <Cells rows={b.rows} />;
  if (b.type === "image") {
    return <>
      {b.picture_url ? <img src={b.picture_url} alt={b.text || "Picture from the document"} /> : <p>(a picture or chart the browser can't show)</p>}
      {b.text && <div className="part-card__caption">{b.text}</div>}
    </>;
  }
  return <p>{b.text}</p>;
}

/** "What I read": every page with what recognition found on it, outlined and listed. */
export function Viewer({ doc, name, onClose }: { doc: Doc; name: string; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [pages, setPages] = useState<Page[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [index, setIndex] = useState(0);
  const [mode, setMode] = useState<Mode>("layout");
  const [hot, setHot] = useState<string | null>(null);
  const shapes = useRef<Record<string, Element | null>>({});
  const rows = useRef<Record<string, HTMLLIElement | null>>({});
  const touch = useTouch();

  useEffect(() => {
    if (dialog.current && !dialog.current.open) dialog.current.showModal();
    api<Page[]>(`/documents/${doc.doc_id}/pages`).then(setPages).catch((err) => setError((err as Error).message));
  }, [doc.doc_id]);

  const scans = doc.format_type !== "typed";
  const hasRegions = !!pages?.some((p) => p.regions?.length);
  const modes: Mode[] = scans ? (hasRegions ? ["layout", "lines", "spacing"] : ["lines", "spacing"]) : ["layout", "spacing"];
  const current = modes.includes(mode) ? mode : modes[0];
  const page = pages?.[index];

  // ---------- what this page shows in the current mode ----------
  let parts: Part[] = [];
  let legend: [string, string][] = [];
  let info = "";
  let heading = "";
  let plain: string | null = null;   // a page shown as text only
  let onImage = false;

  if (page) {
    info = `Page ${page.page} of ${pages!.length} · read with ${Math.round(page.conf * 100)}% confidence`;
    if (current === "spacing") {
      info = `Page ${page.page} of ${pages!.length} · spacing and columns kept`;
    } else if (!scans) {
      legend = Object.entries(BLOCK).map(([t, [n]]) => [`t-${t}`, n.toLowerCase()]);
      const counts = Object.keys(BLOCK).map((t) => [t, page.blocks.filter((b) => b.type === t).length] as const).filter(([, n]) => n);
      info = `Page ${page.page} of ${pages!.length} · ${counts.map(([t, n]) => plural(n, BLOCK[t])).join(", ") || "no text"}`;
      onImage = !!page.image_url && page.blocks.every((b) => b.box);
      heading = `What I found · ${parts_(page.blocks.length)}`;
      parts = page.blocks.map((b, i) => ({
        key: `b${i}`, cls: `t-${b.type}`, box: onImage ? b.box : null, tip: `${BLOCK[b.type][0]}: ${blockSummary(b).slice(0, 200)}`,
        row: <><span className="kind">{BLOCK[b.type][0]}</span><span className="ltext">{blockSummary(b)}</span></>,
        card: blockCard(b),
      }));
      if (!page.blocks.length) plain = page.text || "(this page has no text)";
    } else if (current === "layout" && page.regions?.length && page.image_url) {
      const types = Object.keys(REGION).filter((t) => page.regions.some((r) => r.type === t));
      legend = types.map((t) => [`r-${t}`, REGION[t][0].toLowerCase()]);
      info = `Page ${page.page} of ${pages!.length} · ` + types.map((t) => plural(page.regions.filter((r) => r.type === t).length, REGION[t])).join(", ");
      onImage = true;
      heading = `Layout · ${parts_(page.regions.length)} in reading order`;
      parts = page.regions.map((r, i) => {
        const label = REGION[r.type]?.[0] ?? r.type;
        const conf = r.type === "figure" && !r.text ? "" : ` · ${Math.round(r.conf * 100)}%`;
        return {
          key: `r${i}`, cls: `r-${r.type}`, box: r.box, tip: `${label}: ${(r.text || "").slice(0, 200)}`,
          row: <div className="stack">
            <div><span className="kind">{i + 1}. {label}</span><span className="mono muted">{conf}</span></div>
            {r.type === "table" && r.rows?.length ? <Cells rows={r.rows} /> : r.text ? <span className="ltext">{r.text}</span> : null}
          </div>,
        };
      });
    } else if (!page.image_url) {
      plain = page.text || "(this page has no text)";
    } else {
      legend = (["high", "mid", "low"] as const).map((t) => [`tone-${t}`, CONF_WORD[t]]);
      onImage = true;
      heading = page.lines.length ? `What I read · ${page.lines.length} lines` : "Text on this page";
      parts = page.lines.map((l, i) => ({
        key: `l${i}`, cls: `tone-${confTone(l.conf)}`, box: l.box, tip: `${Math.round(l.conf * 100)}%  ${l.text}`,
        row: <><span className="kind kind--num">{Math.round(l.conf * 100)}%</span><span className="ltext">{l.text}</span></>,
      }));
      if (!page.lines.length) plain = null;
    }
  }

  const enter = (key: string, fromShape: boolean) => {
    setHot(key);
    if (fromShape) rows.current[key]?.scrollIntoView({ block: "nearest" });
  };
  const goTo = (key: string) => shapes.current[key]?.scrollIntoView({ block: "center", behavior: "smooth" });
  const turn = (to: number) => { setIndex(to); setHot(null); };

  const side = page && current !== "spacing" && (parts.length > 0 || (onImage && !plain)) && (
    <aside className="viewer__side">
      <h4 className="mono">{heading}{parts.length > 0 && ` (${touch ? "tap" : "hover"} to find them)`}</h4>
      {parts.length > 0 ? (
        <ol className="parts">
          {parts.map((p) => (
            <li key={p.key} ref={(n) => { rows.current[p.key] = n; }} className={`${p.cls}${hot === p.key ? " is-hot" : ""}`}
                onMouseEnter={() => enter(p.key, false)} onMouseLeave={() => setHot(null)} onClick={() => goTo(p.key)}>
              {p.row}
            </li>
          ))}
        </ol>
      ) : <pre className="plain">{page.text || "(no text)"}</pre>}
    </aside>
  );

  let left: ReactNode = null;
  if (page) {
    if (current === "spacing") left = <pre className="mono-page">{page.layout_text || page.text || "(this page has no text)"}</pre>;
    else if (plain !== null && !onImage) left = <div className="paper"><pre className="plain">{plain}</pre></div>;
    else if (onImage) {
      left = (
        <div className="frame">
          <img src={page.image_url!} alt={`Page ${page.page} of ${name}`} />
          <svg viewBox="0 0 1 1" preserveAspectRatio="none">
            {parts.filter((p) => p.box).map((p) => {
              const [x0, y0, x1, y1] = p.box!;
              return (
                <rect key={p.key} ref={(n) => { shapes.current[p.key] = n; }} x={x0} y={y0} width={x1 - x0} height={y1 - y0}
                      className={`${p.cls}${hot === p.key ? " is-hot" : ""}`} onMouseEnter={() => enter(p.key, true)} onMouseLeave={() => setHot(null)}
                      onClick={() => enter(p.key, true)}>
                  <title>{p.tip}</title>
                </rect>
              );
            })}
          </svg>
        </div>
      );
    } else {
      left = (
        <div className="paper">
          {parts.map((p) => (
            <div key={p.key} ref={(n) => { shapes.current[p.key] = n; }} className={`part-card ${p.cls}${hot === p.key ? " is-hot" : ""}`}
                 onMouseEnter={() => enter(p.key, true)} onMouseLeave={() => setHot(null)}>
              <span className="part-card__tag mono">{p.tip.split(":")[0]}</span>
              {p.card}
            </div>
          ))}
        </div>
      );
    }
  }

  return (
    <dialog ref={dialog} className="viewer" aria-labelledby="v-title" onClose={onClose}>
      <div className="viewer__head">
        <div className="viewer__title">
          <p className="eyebrow">What I read</p>
          <h3 id="v-title">{name} <span className="muted">· {FORMAT[doc.format_type]}</span></h3>
        </div>
        {pages && modes.length > 1 && (
          <Tray label="How to show the page" options={modes.map((m) => [m, MODE_NAMES[m]])} value={current} onChange={(m) => { setMode(m); setHot(null); }} small />
        )}
        <DownloadMenu docId={doc.doc_id} compact />
        <Knob onClick={() => dialog.current?.close()} aria-label="Close" title="Close" className="knob--close"><X size={17} /></Knob>
      </div>
      <div className="viewer__bar">
        {legend.length > 0 && (
          <div className="legend" aria-label="What the colours mean">
            {legend.map(([cls, text]) => <span key={cls} className={cls}><i aria-hidden="true" />{text}</span>)}
          </div>
        )}
        <span className="mono muted viewer__info">{info}</span>
        {pages && pages.length > 1 && (
          <div className="pager">
            <Push size="sm" icon onClick={() => turn(index - 1)} disabled={index === 0} aria-label="Previous page"><ChevronLeft size={17} /></Push>
            <span className="mono">{index + 1} / {pages.length}</span>
            <Push size="sm" icon onClick={() => turn(index + 1)} disabled={index === pages.length - 1} aria-label="Next page"><ChevronRight size={17} /></Push>
          </div>
        )}
      </div>
      <div className={`viewer__body${side ? "" : " is-single"}`}>
        {error ? <p className="placeholder">{error}</p> : !page ? <p className="placeholder">Opening your document…</p> : (
          <>
            <div className="viewer__page">{left}</div>
            {side}
          </>
        )}
      </div>
    </dialog>
  );
}
