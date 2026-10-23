import type { Doc } from "./types";

/** crypto.randomUUID only exists on https and localhost; a phone on the local network gets the fallback. */
export function uuid(): string {
  if (typeof crypto.randomUUID === "function" && window.isSecureContext) return crypto.randomUUID();
  return "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (c) =>
    (+c ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (+c / 4)))).toString(16));
}

function storedId(store: () => Storage, key: string): string {
  try {
    const s = store();
    let id = s.getItem(key);
    if (!id) { id = uuid(); s.setItem(key, id); }
    return id;
  } catch { return uuid(); }
}

// One session per tab (its documents are private to it), one visitor id per browser (for the counts).
export const SESSION_ID = storedId(() => sessionStorage, "sessionId");
export const VISITOR_ID = storedId(() => localStorage, "visitorId");

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = { ...(options.headers as Record<string, string> | undefined), "X-Session-Id": SESSION_ID };
  const resp = await fetch(path, { ...options, headers });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Something went wrong (${resp.status})`);
  return body as T;
}

export function postJson<T>(path: string, data: unknown): Promise<T> {
  return api<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
}

// ---------- names ----------

/** The server stores uploads as "<doc_id>_<original name>.<ext>". */
export function nameFromPath(doc: Doc): string {
  const base = doc.file_path.split(/[\\/]/).pop() ?? doc.doc_id;
  return base.startsWith(doc.doc_id + "_") ? base.slice(doc.doc_id.length + 1) : base;
}

/** The name a file gets on the server (routers/upload.py: safe_name), to spot re-uploads. */
export function storedName(name: string): string {
  const dot = name.lastIndexOf(".");
  const [stem, ext] = dot > 0 ? [name.slice(0, dot), name.slice(dot).toLowerCase()] : [name, ""];
  return (stem.replace(/[^A-Za-z0-9._-]+/g, "_").slice(0, 80) || "document") + ext;
}

export const extOf = (name: string) => name.split(".").pop()?.toLowerCase() ?? "";

export function kindOf(name: string): [string, string] {
  const ext = extOf(name);
  if (ext === "pdf") return ["pdf", "PDF"];
  if (["jpg", "jpeg", "png", "tif", "tiff", "bmp", "webp"].includes(ext)) return ["image", "IMG"];
  if (ext === "docx") return ["docx", "DOC"];
  if (ext === "pptx") return ["pptx", "PPT"];
  return ["txt", "TXT"];
}

export function sizeText(bytes: number): string {
  return bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

// ---------- uploads ----------

// Photos are shrunk in the browser before upload: phone photos are often 3-12 MB, while
// 2600 px on the long side at JPEG quality 85 keeps every letter readable for OCR
// (the server resizes pages to about A4 anyway). PDFs and Office files are sent as they are.
export const SHRINK_TYPES = ["image/jpeg", "image/png", "image/webp", "image/bmp"];
const MAX_SIDE = 2600;
export const SHRINK_ABOVE = 700 * 1024;

export async function shrinkPhoto(file: File): Promise<File> {
  if (!SHRINK_TYPES.includes(file.type) || file.size < SHRINK_ABOVE || !window.createImageBitmap) return file;
  try {
    const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });  // phone photos upright
    const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    const ctx = canvas.getContext("2d")!;
    ctx.fillStyle = "#fff";  // transparent PNGs: white paper, not black
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close?.();
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.85));
    if (!blob || blob.size >= file.size) return file;  // never send something bigger
    return new File([blob], file.name.replace(/\.[^.]+$/, "") + ".jpg", { type: "image/jpeg" });
  } catch { return file; }  // the server can still read the original
}

/** fetch() cannot report upload progress; XMLHttpRequest can. */
export function uploadWithProgress(form: FormData, onProgress: (fraction: number) => void): Promise<Doc> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/upload");
    xhr.setRequestHeader("X-Session-Id", SESSION_ID);
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded / e.total); };
    xhr.upload.onload = () => onProgress(1);
    xhr.onload = () => {
      let body: { detail?: unknown } = {};
      try { body = JSON.parse(xhr.responseText); } catch { /* not JSON */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as Doc);
      else reject(new Error(typeof body.detail === "string" ? body.detail : `Something went wrong (${xhr.status})`));
    };
    xhr.onerror = () => reject(new Error("Upload failed. Check your internet connection and try again."));
    xhr.send(form);
  });
}

// ---------- downloads (layout text keeps spacing; csv = tables) ----------

export const DOWNLOADS: [string, string][] = [
  ["layout", "Layout text (spacing kept)"], ["md", "Markdown"], ["csv", "Tables (CSV)"], ["json", "JSON (everything)"], ["txt", "Plain text"],
];

export async function downloadExport(docId: string, format: string): Promise<void> {
  const resp = await fetch(`/documents/${docId}/export?format=${format}`, { headers: { "X-Session-Id": SESSION_ID } });
  if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).detail || `Download failed (${resp.status})`);
  const name = (resp.headers.get("content-disposition") || "").match(/filename="([^"]+)"/)?.[1] || `document.${format}`;
  const url = URL.createObjectURL(await resp.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}
