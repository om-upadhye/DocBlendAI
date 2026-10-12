// Calls to the DocBlendAI server: the same API the website uses.
import AsyncStorage from '@react-native-async-storage/async-storage';

import {SERVER_URL, USER_ID} from './config';
import type {Reliability} from './theme';

export type FormatType = 'typed' | 'scanned' | 'handwritten';

export type Doc = {doc_id: string; file_path: string; format_type: FormatType; page_count: number};

export type Line = {text: string; conf: number; box: number[]};
export type Block = {type: 'paragraph' | 'table' | 'image'; text: string; rows?: string[][] | null};
export type Page = {page: number; text: string; conf: number; image_url: string | null; lines: Line[]; blocks: Block[]};

export type Answer = {answer_id: string; answer_text: string; reliability_label: Reliability};
export type Source = {
  chunk_id: string;
  doc_id: string;
  content_type: string;
  text: string;
  similarity: number;
  confidence: number;
  combined_score: number;
};
export type Stats = {visitors_today: number; questions_today: number; visitors_total: number; questions_total: number};
export type UploadFile = {uri: string; name: string; type: string};

function uuid(): string {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
    const r = Math.floor(Math.random() * 16);
    return (c === 'x' ? r : 8 + (r % 4)).toString(16);
  });
}

// One session per app launch: the server deletes its documents once the app stops sending heartbeats.
export const SESSION_ID = uuid();

let visitorId: string | null = null;
async function getVisitorId(): Promise<string> {
  if (visitorId) {
    return visitorId;
  }
  try {
    visitorId = await AsyncStorage.getItem('visitorId');
    if (!visitorId) {
      visitorId = uuid();
      await AsyncStorage.setItem('visitorId', visitorId);
    }
  } catch {
    visitorId = uuid();
  }
  return visitorId;
}

export function absoluteUrl(path: string): string {
  return SERVER_URL + path;
}

// The original upload's name: the server stores files as "<doc_id>_<name>.<ext>".
export function docName(doc: Doc): string {
  const base = doc.file_path.split(/[\\/]/).pop() || doc.doc_id;
  return base.startsWith(doc.doc_id + '_') ? base.slice(doc.doc_id.length + 1) : base;
}

async function request<T>(path: string, init: RequestInit = {}, timeoutMs = 60000): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let resp: Response;
  try {
    resp = await fetch(absoluteUrl(path), {
      ...init,
      headers: {...(init.headers as Record<string, string>), 'X-Session-Id': SESSION_ID},
      signal: controller.signal,
    });
  } catch {
    throw new Error("Can't reach the server. Check your internet connection and try again.");
  } finally {
    clearTimeout(timer);
  }
  const text = await resp.text();
  let body: any = {};
  try {
    body = text ? JSON.parse(text) : {};
  } catch {}
  if (!resp.ok) {
    throw new Error(typeof body.detail === 'string' ? body.detail : `Something went wrong (${resp.status})`);
  }
  return body as T;
}

const json = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify(body),
});

export async function heartbeat(timeoutMs = 90000): Promise<{public_demo: boolean; heartbeat_seconds: number}> {
  // Long timeout: a free Render server takes up to a minute to wake up.
  return request('/session/heartbeat', json({session_id: SESSION_ID, visitor_id: await getVisitorId()}), timeoutMs);
}

export const getStats = () => request<Stats>('/stats');
export const listDocuments = () => request<Doc[]>('/documents');
export const deleteDocument = (docId: string) => request<void>(`/documents/${docId}`, {method: 'DELETE'});
export const getPages = (docId: string) => request<Page[]>(`/documents/${docId}/pages`);

export function uploadDocument(file: UploadFile, formatHint: FormatType | null): Promise<Doc> {
  const form = new FormData();
  form.append('file', file as any); // React Native sends {uri, name, type} as a file part
  if (formatHint) {
    form.append('format_hint', formatHint);
  }
  return request<Doc>('/upload', {method: 'POST', body: form}, 10 * 60000); // OCR of scans can take minutes
}

export async function ask(question: string, docIds: string[]): Promise<{answer: Answer; sources: Source[]}> {
  const answer = await request<Answer>(
    '/ask',
    json({query_id: uuid(), question_text: question, user_id: USER_ID, doc_ids: docIds}),
    120000,
  );
  let sources: Source[] = [];
  try {
    sources = await request<Source[]>(`/answer/${answer.answer_id}/sources`);
  } catch {}
  return {answer, sources};
}
