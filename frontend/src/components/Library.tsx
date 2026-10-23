import { Check, CircleAlert, Eye, FileStack, Lock, Plus, Trash2, Upload } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";
import { SHRINK_ABOVE, SHRINK_TYPES, kindOf, shrinkPhoto, sizeText, storedName, uploadWithProgress } from "../api";
import type { Doc, FormatType } from "../types";
import { FORMAT, STEPS } from "../words";
import { Knob, Push, Switch, Tray } from "./Keys";

type Hint = "" | FormatType;
const HINTS: [Hint, string][] = [["", "Auto"], ["typed", "Typed"], ["scanned", "Printed"], ["handwritten", "Handwritten"]];
const ACCEPT = ".pdf,.jpg,.jpeg,.png,.tif,.tiff,.bmp,.webp,.docx,.pptx,.txt";

interface Job { id: number; name: string; msg: string; state: "busy" | "ok" | "err" }

export function Library({ docs, names, selected, onSelect, previewId, onPreview, onRead, onDelete, onUploaded, publicDemo, touch }: {
  docs: Doc[];
  names: Record<string, string>;
  selected: Set<string>;
  onSelect: (id: string, on: boolean) => void;
  previewId: string | null;
  onPreview: (doc: Doc) => void;
  onRead: (doc: Doc) => void;
  onDelete: (doc: Doc) => void;
  onUploaded: (lastId: string) => void;
  publicDemo: boolean;
  touch: boolean;
}) {
  const [hint, setHint] = useState<Hint>("");
  const [jobs, setJobs] = useState<Job[]>([]);
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const nextJob = useRef(0);

  const patch = (id: number, change: Partial<Job>) => setJobs((all) => all.map((j) => (j.id === id ? { ...j, ...change } : j)));

  async function uploadOne(file: File): Promise<string | null> {
    const id = ++nextJob.current;
    setJobs((all) => [{ id, name: file.name, msg: "Preparing…", state: "busy" }, ...all]);
    const original = file.size;
    if (SHRINK_TYPES.includes(file.type) && original >= SHRINK_ABOVE) patch(id, { msg: "Shrinking photo…" });
    file = await shrinkPhoto(file);
    const note = file.size < original ? ` Photo shrunk ${sizeText(original)} → ${sizeText(file.size)}.` : "";

    let uploaded = 0, readingSince: number | null = null, step = 1;
    const show = () => {
      if (readingSince === null) { patch(id, { msg: `Uploading ${Math.round(uploaded * 100)}% of ${sizeText(file.size)}…` }); return; }
      const secs = Math.round((Date.now() - readingSince) / 1000);  // server side: reading takes a few seconds per page
      if (secs > 3 + (step - 1) * 5 && step < STEPS.length - 1) step++;
      patch(id, { msg: `${STEPS[step]}… ${secs}s` });
    };
    const timer = setInterval(show, 500);
    show();
    const form = new FormData();
    form.append("file", file);
    if (hint) form.append("format_hint", hint);
    try {
      const doc = await uploadWithProgress(form, (fraction) => {
        uploaded = fraction;
        if (fraction >= 1 && readingSince === null) readingSince = Date.now();
        show();
      });
      clearInterval(timer);
      const pages = `${doc.page_count} ${FORMAT[doc.format_type].toLowerCase()} page${doc.page_count > 1 ? "s" : ""}`;
      patch(id, { state: "ok", msg: `All set! I read ${pages}.${note}` });
      setTimeout(() => setJobs((all) => all.filter((j) => j.id !== id)), 8000);
      return doc.doc_id;
    } catch (err) {
      clearInterval(timer);
      patch(id, { state: "err", msg: (err as Error).message });
      return null;
    }
  }

  async function uploadAll(files: File[]) {
    let lastId: string | null = null;
    const have = Object.values(names);
    for (const file of files) {
      // A second copy adds nothing to answers and only repeats the same passages.
      if (have.includes(storedName(file.name)) && !confirm(`"${file.name}" is already in your documents. Upload it again anyway?`)) continue;
      const id = await uploadOne(file);
      if (id) lastId = id;
    }
    if (lastId) onUploaded(lastId);
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    uploadAll([...e.dataTransfer.files]);
  };

  return (
    <section className="panel panel--docs" aria-labelledby="docs-title">
      <header className="panel__head">
        <p className="eyebrow">01 · Library</p>
        <h2 id="docs-title">Your notes</h2>
        <p className="panel__lede">Typed, printed or handwritten. Share them and I'll read them through.</p>
      </header>

      <input ref={input} type="file" className="sr" multiple accept={ACCEPT}
             onChange={(e) => { uploadAll([...(e.target.files ?? [])]); e.target.value = ""; }} />
      <div className={`drop${over ? " is-over" : ""}`}
           onDragEnter={(e) => { e.preventDefault(); setOver(true); }} onDragOver={(e) => { e.preventDefault(); setOver(true); }}
           onDragLeave={(e) => { e.preventDefault(); setOver(false); }} onDrop={onDrop}>
        <span className="drop__well" aria-hidden="true"><Upload size={22} /></span>
        <p className="drop__title">{touch ? "Add a PDF or a photo of your notes" : "Drop files here, or"}</p>
        <Push variant="primary" onClick={() => input.current?.click()}>
          <Plus size={18} aria-hidden="true" /> {touch ? "Add notes" : "Choose files"}
        </Push>
        <p className="drop__types">PDF · photo · Word · PowerPoint · text</p>
      </div>

      <div className="field-row">
        <span className="field-row__label" id="hint-label">Writing</span>
        <Tray label="What kind of writing?" options={HINTS} value={hint} onChange={setHint} small />
      </div>

      {publicDemo && (
        <p className="note note--private"><Lock size={14} aria-hidden="true" /> Only you can see your files. They're deleted shortly after you leave.</p>
      )}

      <div className="jobs" aria-live="polite">
          {jobs.map((j) => (
            <div key={j.id} className={`job job--${j.state}`}>
              {j.state === "busy" ? <span className="spinner" aria-hidden="true" /> : j.state === "ok" ? <Check size={16} aria-hidden="true" /> : <CircleAlert size={16} aria-hidden="true" />}
              <div className="job__body">
                <div className="job__name">{j.name}</div>
                <div className="job__msg">{j.msg}</div>
              </div>
            </div>
          ))}
      </div>

      <div className="docs-head">
        <h3>Library</h3>
        {docs.length > 0 && <span className="mono">{docs.length} document{docs.length > 1 ? "s" : ""}</span>}
      </div>
      {docs.length === 0 ? (
        <div className="empty">
          <FileStack size={30} aria-hidden="true" />
          <p>Nothing here yet. Add a note and it'll show up here.</p>
        </div>
      ) : (
        <ul className="docs">
            {[...docs].reverse().map((d) => {  // newest first
              const name = names[d.doc_id];
              const [kind, short] = kindOf(name);
              const on = selected.has(d.doc_id);
              return (
                <li key={d.doc_id}
                    className={`doc${on ? " is-on" : ""}${previewId === d.doc_id ? " is-viewing" : ""}`}>
                  <button type="button" className="doc__main" onClick={() => onPreview(d)} title="Show in preview">
                    <span className={`stamp stamp--${kind}`} aria-hidden="true">{short}</span>
                    <span className="doc__meta">
                      <span className="doc__name">{name}</span>
                      <span className="doc__sub">
                        <span className={`fmt fmt--${d.format_type}`}>{FORMAT[d.format_type]}</span>
                        <span>{d.page_count} page{d.page_count > 1 ? "s" : ""}</span>
                      </span>
                    </span>
                  </button>
                  <div className="doc__acts">
                    <Knob onClick={() => onRead(d)} title="See what I read on each page" aria-label={`See what I read in ${name}`}><Eye size={17} /></Knob>
                    <Knob className="knob--danger" onClick={() => onDelete(d)} title="Remove" aria-label={`Remove ${name}`}><Trash2 size={16} /></Knob>
                  </div>
                  <div className="doc__foot">
                    <Switch on={on} onChange={(v) => onSelect(d.doc_id, v)}>Ask about this</Switch>
                  </div>
                </li>
              );
            })}
        </ul>
      )}
    </section>
  );
}
