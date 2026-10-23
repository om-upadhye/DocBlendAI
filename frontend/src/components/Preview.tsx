import { ArrowRight, Maximize2, ScanText, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api, extOf } from "../api";
import type { Doc, Page, PageSet } from "../types";
import { DownloadMenu } from "./DownloadMenu";
import { Knob, Push } from "./Keys";

const BROWSER_IMAGES = ["jpg", "jpeg", "png", "webp"];

export function PageFigure({ page, word, total, name, onOpen }: {
  page: PageSet["pages"][number]; word: string; total: number; name: string; onOpen?: () => void;
}) {
  const caption = `${word} ${page.page} of ${total}`;
  return (
    <figure className="sheet">
      {page.image_url ? (
        <img src={page.image_url} alt={`${caption} of ${name}`} loading="lazy" onClick={onOpen} />
      ) : (
        <div className="sheet__text" onClick={onOpen}><pre>{page.text || "(nothing written on this page)"}</pre></div>
      )}
      <figcaption className="mono">{caption}</figcaption>
    </figure>
  );
}

/** The original document, kept open beside the chat: our own page view, never the browser's PDF viewer. */
export function Preview({ doc, name, onOpenWindow, onRead, onClose, onAsk, phone }: {
  doc: Doc | null;
  name: string;
  onOpenWindow: (set: PageSet, index: number) => void;
  onRead: (doc: Doc) => void;
  onClose: () => void;
  onAsk: () => void;
  phone: boolean;
}) {
  const [set, setSet] = useState<PageSet | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setSet(null);
    setError(null);
    if (!doc) return;
    const ext = extOf(name);
    const fileUrl = `/documents/${doc.doc_id}/file`;
    if (BROWSER_IMAGES.includes(ext)) {
      setSet({ docId: doc.doc_id, name, word: "Page", pages: [{ page: 1, image_url: fileUrl, text: "" }] });
      return;
    }
    let live = true;
    api<Page[]>(`/documents/${doc.doc_id}/pages`)
      .then((pages) => { if (live) setSet({ docId: doc.doc_id, name, word: ext === "pptx" ? "Slide" : "Page", pages }); })
      .catch((err) => { if (live) setError((err as Error).message); });
    return () => { live = false; };
  }, [doc?.doc_id, name]);  // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <section className="panel panel--preview" aria-labelledby="p-title">
      <header className="panel__head panel__head--row">
        <div className="panel__title">
          <p className="eyebrow">02 · Preview</p>
          <h2 id="p-title" title={doc ? name : undefined}>{doc ? name : "Preview"}</h2>
        </div>
        <Knob onClick={onClose} aria-label="Close the preview" title="Close preview" className="knob--close"><X size={17} /></Knob>
      </header>
      {doc && (
        <div className="toolbar">
          <Push size="sm" onClick={() => set && onOpenWindow(set, 0)} disabled={!set}><Maximize2 size={15} aria-hidden="true" /> Open</Push>
          <Push size="sm" onClick={() => onRead(doc)}><ScanText size={15} aria-hidden="true" /> What I read</Push>
          <DownloadMenu docId={doc.doc_id} compact={phone} />
          {phone && <Push size="sm" variant="primary" onClick={onAsk}>Ask <ArrowRight size={15} aria-hidden="true" /></Push>}
        </div>
      )}
      <div className="preview-well">
        {!doc ? (
          <div className="placeholder">Pick a document and I'll keep it open here while we talk about it.</div>
        ) : error ? (
          <div className="placeholder">{error}</div>
        ) : !set ? (
          <div className="sheets"><div className="sheet skeleton" /></div>
        ) : (
          <div className="sheets">
            {set.pages.map((p, i) => (
              <PageFigure key={p.page} page={p} word={set.word} total={set.pages.length} name={name} onOpen={() => onOpenWindow(set, i)} />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
