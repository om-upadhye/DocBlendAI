import { ChevronDown, Download } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { DOWNLOADS, downloadExport } from "../api";
import { Push } from "./Keys";

/** "Download" key that opens a small menu of export formats. */
export function DownloadMenu({ docId, compact = false }: { docId: string; compact?: boolean }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") { e.stopPropagation(); setOpen(false); } };
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", esc, true);
    return () => { document.removeEventListener("pointerdown", away); document.removeEventListener("keydown", esc, true); };
  }, [open]);

  const pick = async (format: string) => {
    setBusy(format);
    try { await downloadExport(docId, format); setOpen(false); }
    catch (err) { alert((err as Error).message); }
    finally { setBusy(null); }
  };

  return (
    <div className="menu" ref={box}>
      <Push size="sm" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)} title="Download what I read">
        <Download size={16} aria-hidden="true" />
        {!compact && <span>Download</span>}
        <ChevronDown size={14} aria-hidden="true" className={`menu__chev${open ? " is-open" : ""}`} />
      </Push>
      {open && (
        <ul className="menu__list" role="menu">
          {DOWNLOADS.map(([format, label]) => (
            <li key={format}>
              <button type="button" role="menuitem" onClick={() => pick(format)} disabled={busy !== null}>
                <span className="menu__ext">.{format === "layout" ? "txt" : format}</span>
                {label}
                {busy === format && <span className="spinner" aria-label="Preparing" />}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
