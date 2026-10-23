import { Eye, FolderOpen, MessageCircle } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { SESSION_ID, VISITOR_ID, api, nameFromPath, postJson } from "./api";
import { Chat } from "./components/Chat";
import { DocWindow, WindowChip, type Minimized, type WindowPlace } from "./components/DocWindow";
import { ThemeToggle } from "./components/Keys";
import { Library } from "./components/Library";
import { Preview } from "./components/Preview";
import { Viewer } from "./components/Viewer";
import { useIsPhone, useSlider, useTouch } from "./hooks";
import type { Doc, PageSet } from "./types";

type View = "docs" | "preview" | "chat";

// Which documents questions go to, remembered in this browser only.
function savedSelection(): string[] {
  try { return JSON.parse(localStorage.getItem("selectedDocs") || "[]"); } catch { return []; }
}
function saveSelection(ids: Set<string>) {
  try { localStorage.setItem("selectedDocs", JSON.stringify([...ids])); } catch { /* not remembered */ }
}

export default function App() {
  const phone = useIsPhone();
  const touch = useTouch();
  const [docs, setDocs] = useState<Doc[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [previewClosed, setPreviewClosed] = useState(false);
  const [view, setView] = useState<View>("docs");
  const [viewing, setViewing] = useState<Doc | null>(null);
  const [win, setWin] = useState<{ set: PageSet; at: WindowPlace; key: number } | null>(null);
  const [chip, setChip] = useState<Minimized | null>(null);
  const [publicDemo, setPublicDemo] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const tabTray = useRef<HTMLUListElement>(null);
  const tabKey = useSlider(tabTray, phone ? view : "");

  const names = useMemo(() => Object.fromEntries(docs.map((d) => [d.doc_id, nameFromPath(d)])), [docs]);

  const loadDocs = useCallback(async (newDocId?: string) => {
    const list = await api<Doc[]>("/documents");  // oldest first
    const ids = new Set(list.map((d) => d.doc_id));
    let sel = newDocId ? new Set([newDocId]) : new Set(savedSelection().filter((id) => ids.has(id)));
    if (!sel.size && list.length) sel = new Set([list[list.length - 1].doc_id]);
    saveSelection(sel);
    setSelected(sel);
    setDocs(list);
    setPreviewId((current) => newDocId ?? (current && ids.has(current) ? current : list.length ? list[list.length - 1].doc_id : null));
    setChip((c) => (c && !ids.has(c.docId) ? null : c));  // its document was removed
  }, []);

  // Session heartbeat: keeps this tab's documents alive. Closing the tab lets the server delete them
  // after a short grace period (a reload comes back first).
  useEffect(() => {
    let timer = 0;
    const beat = () => postJson<{ public_demo: boolean; heartbeat_seconds: number }>("/session/heartbeat", { session_id: SESSION_ID, visitor_id: VISITOR_ID })
      .then((info) => { setPublicDemo(info.public_demo); return info; }).catch(() => null);
    beat().then((info) => { timer = window.setInterval(beat, ((info && info.heartbeat_seconds) || 60) * 1000); });
    loadDocs().catch((err) => setLoadError((err as Error).message));
    const leave = () => navigator.sendBeacon(`/session/${SESSION_ID}/leave`);
    addEventListener("pagehide", leave);
    return () => { clearInterval(timer); removeEventListener("pagehide", leave); };
  }, [loadDocs]);

  const select = (id: string, on: boolean) => {
    setSelected((s) => {
      const next = new Set(s);
      if (on) next.add(id); else next.delete(id);
      saveSelection(next);
      return next;
    });
  };

  const showPreview = (doc: Doc) => {
    setPreviewId(doc.doc_id);
    setPreviewClosed(false);
    if (phone) setView("preview");
  };

  const remove = async (doc: Doc) => {
    if (!confirm(`Remove "${names[doc.doc_id]}"? I'll stop using it for answers.`)) return;
    try {
      await api(`/documents/${doc.doc_id}`, { method: "DELETE" });
      await loadDocs();
    } catch (err) { alert((err as Error).message); }
  };

  const openWindow = (set: PageSet, index: number) => { setChip(null); setWin({ set, at: { index, zoom: 100 }, key: Date.now() }); };
  const restoreWindow = () => {
    if (!chip) return;
    setWin({ set: chip, at: { scrollTop: chip.scrollTop, zoom: chip.zoom, label: chip.label }, key: Date.now() });
    setChip(null);
  };

  const closePreview = () => {
    setPreviewClosed(true);
    if (phone) setView("docs");
  };

  const previewDoc = docs.find((d) => d.doc_id === previewId) ?? null;
  const selectedIds = [...selected].filter((id) => names[id]);
  const tabs: [View, string, typeof Eye][] = [["docs", "Notes", FolderOpen], ["preview", "Preview", Eye], ["chat", "Ask", MessageCircle]];

  return (
    <>
      <header className="topbar">
        <div className="topbar__in">
          <a className="brand" href="/" aria-label="DocBlendAI home">
            <span className="coin" aria-hidden="true">d</span>
            <span className="brand__name">DocBlend<em>AI</em></span>
          </a>
          <p className="topbar__tag">Notes in, honest answers out.</p>
          <ThemeToggle />
        </div>
      </header>

      {loadError && <p className="banner">{loadError}</p>}

      <main className={`board${previewClosed ? " is-preview-off" : ""}`} data-view={phone ? view : undefined}>
        <Library docs={docs} names={names} selected={selected} onSelect={select} previewId={previewId}
                 onPreview={showPreview} onRead={setViewing} onDelete={remove} publicDemo={publicDemo} touch={touch}
                 onUploaded={(id) => { setPreviewClosed(false); loadDocs(id).then(() => { if (phone) setView("preview"); }); }} />
        {(!previewClosed || phone) && (
          <Preview doc={previewDoc} name={previewDoc ? names[previewDoc.doc_id] : ""} phone={phone}
                   onOpenWindow={openWindow} onRead={setViewing} onClose={closePreview} onAsk={() => setView("chat")} />
        )}
        <Chat selected={selectedIds} names={names} phone={phone} previewClosed={previewClosed}
              onShowPreview={() => setPreviewClosed(false)} />
      </main>

      {phone && (
        <nav className="bottom-nav" aria-label="Sections">
          <ul ref={tabTray} className="tray bottom-nav__tray">
            <li aria-hidden="true" className="tray__key" style={tabKey} />
            {tabs.map(([v, label, Icon]) => {
              const on = view === v;
              return (
                <li key={v}>
                  <button type="button" className={`tray__opt bottom-nav__tab${on ? " is-on" : ""}`} aria-current={on ? "page" : undefined}
                          onClick={() => { setView(v); if (v === "preview") setPreviewClosed(false); }}>
                    <Icon size={21} strokeWidth={on ? 2.3 : 1.8} aria-hidden="true" className="tray__text" />
                    <span className="tray__text">{label}</span>
                    {v === "docs" && docs.length > 0 && <b className="badge">{docs.length}</b>}
                  </button>
                </li>
              );
            })}
          </ul>
        </nav>
      )}

      {win && <DocWindow key={win.key} set={win.set} at={win.at} onMinimize={(saved) => { setWin(null); setChip(saved); }} />}
      {chip && !win && <WindowChip saved={chip} onOpen={restoreWindow} onClose={() => setChip(null)} />}
      {viewing && <Viewer doc={viewing} name={names[viewing.doc_id] ?? ""} onClose={() => setViewing(null)} />}
    </>
  );
}
