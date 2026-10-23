import { ArrowUp, ChevronRight, FileText } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { api, postJson, uuid } from "../api";
import type { Answer, Label, Source } from "../types";
import { CONF_WORD, MATCH_WORD, NOT_FOUND, REL, SUGGESTIONS, confTone, matchTone, pct } from "../words";
import { Push } from "./Keys";

interface Reply { label: Label; text: string; notFound: boolean; from: string[]; sources: Source[] }
interface Message { id: string; me: boolean; text?: string; reply?: Reply; error?: string; pending?: boolean }

function Meter({ label, tone, word, value }: { label: string; tone: string; word: string; value: number }) {
  return <span className={`meter tone-${tone}`} title={`${label}: ${word}`}><i aria-hidden="true" />{label} {pct(value)}</span>;
}

function SourceCard({ s, name, scores }: { s: Source; name: string; scores: boolean }) {
  return (
    <div className="source">
      <div className="source__meta">
        <b>{name}</b><span>{s.content_type}</span>
        {scores && <Meter label="match" tone={matchTone(s.similarity)} word={MATCH_WORD[matchTone(s.similarity)]} value={s.similarity} />}
        {scores && <Meter label="legibility" tone={confTone(s.confidence)} word={CONF_WORD[confTone(s.confidence)]} value={s.confidence} />}
      </div>
      <pre>{s.text}</pre>
    </div>
  );
}

function ReplyBody({ reply, names }: { reply: Reply; names: Record<string, string> }) {
  const r = REL[reply.label];
  return (
    <>
      <span className={`verdict verdict--${reply.label}`}><span className="led is-on" aria-hidden="true" />{r.title}</span>
      <div className="bubble__text">{reply.text}</div>
      <p className="bubble__why">{r.why}</p>
      {!reply.notFound && <p className="bubble__from mono">From: {reply.from.map((id) => names[id] ?? id.slice(0, 8)).join(", ")}</p>}
      {reply.sources.length > 0 && (
        // Any question scores some similarity against any text (even gibberish reaches ~60%),
        // so on a not-found answer the scores would only suggest a match that is not there.
        <details className="sources">
          <summary><ChevronRight size={15} aria-hidden="true" />{reply.notFound ? "Closest passages" : "Where I found this"} ({reply.sources.length})</summary>
          {reply.notFound && <p className="bubble__why">None of these answer your question; they are just the nearest text in your notes.</p>}
          {reply.sources.map((s) => <SourceCard key={s.chunk_id} s={s} name={names[s.doc_id] ?? s.doc_id.slice(0, 8)} scores={!reply.notFound} />)}
        </details>
      )}
    </>
  );
}

export function Chat({ selected, names, previewClosed, onShowPreview, phone }: {
  selected: string[];
  names: Record<string, string>;
  previewClosed: boolean;
  onShowPreview: () => void;
  phone: boolean;
}) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [nudge, setNudge] = useState(false);
  const log = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLTextAreaElement>(null);

  useEffect(() => { log.current?.scrollTo({ top: log.current.scrollHeight, behavior: "smooth" }); }, [messages]);
  useEffect(() => { if (selected.length) setNudge(false); }, [selected.length]);

  async function ask(q: string) {
    if (!selected.length) { setNudge(true); return; }
    const docIds = [...selected];
    const id = uuid();
    setMessages((m) => [...m, { id: id + "q", me: true, text: q }, { id, me: false, pending: true }]);
    setBusy(true);
    const settle = (change: Partial<Message>) => setMessages((m) => m.map((x) => (x.id === id ? { ...x, pending: false, ...change } : x)));
    try {
      const answer = await postJson<Answer>("/ask", { query_id: uuid(), question_text: q, user_id: "web", doc_ids: docIds });
      const sources = await api<Source[]>(`/answer/${answer.answer_id}/sources`);
      settle({ reply: { label: answer.reliability_label, text: answer.answer_text, notFound: answer.answer_text === NOT_FOUND, from: docIds, sources } });
    } catch (err) {
      settle({ error: (err as Error).message });
    } finally {
      setBusy(false);
    }
  }

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const q = question.trim();
    if (!q || busy) return;
    setQuestion("");
    if (box.current) box.current.style.height = "";
    ask(q);
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !phone) { e.preventDefault(); submit(); }
  };
  const grow = () => {
    const t = box.current;
    if (!t) return;
    t.style.height = "auto";
    t.style.height = Math.min(t.scrollHeight, 150) + "px";
  };

  return (
    <section className="panel panel--chat" aria-labelledby="ask-title">
      <header className="panel__head panel__head--row">
        <div className="panel__title">
          <p className="eyebrow">03 · Conversation</p>
          <h2 id="ask-title">Let's talk about your notes</h2>
        </div>
        {previewClosed && !phone && (
          <Push size="sm" onClick={onShowPreview}><FileText size={15} aria-hidden="true" /> Show preview</Push>
        )}
      </header>

      <div className={`scope${!selected.length ? " scope--none" : ""}${nudge ? " is-nudged" : ""}`} aria-live="polite">
        {selected.length ? (
          <>
            <span className="mono">Reading from</span>
            {selected.map((id) => <span key={id} className="chip">{names[id] ?? id.slice(0, 8)}</span>)}
          </>
        ) : (
          <span>Switch on “Ask about this” for a document so I know which one you mean.</span>
        )}
      </div>

      <div className="log" ref={log} aria-live="polite">
        {messages.length === 0 && (
          <div className="welcome">
            <p className="welcome__mark" aria-hidden="true">“</p>
            <h3>Ask me anything about your notes.</h3>
            <p>I'll answer from what's written there, tell you honestly how sure I am, and show you exactly where I found it.</p>
          </div>
        )}
          {messages.map((m) => (
            <div key={m.id} className={`msg${m.me ? " msg--me" : ""}`}>
              <div className="bubble">
                {m.me ? m.text
                  : m.pending ? <span className="typing" aria-label="Thinking"><i /><i /><i /></span>
                  : m.error ? <><span className="verdict verdict--Unreadable"><span className="led is-on" aria-hidden="true" />Sorry</span><div className="bubble__text">{m.error}</div></>
                  : m.reply && <ReplyBody reply={m.reply} names={names} />}
              </div>
            </div>
          ))}
      </div>

      {selected.length > 0 && messages.length === 0 && (
        <div className="suggest">
          {SUGGESTIONS.map((q) => <button key={q} type="button" className="keycap" onClick={() => ask(q)}>{q}</button>)}
        </div>
      )}

      <form className="composer" onSubmit={submit}>
        <label htmlFor="question" className="sr">Your question</label>
        <div className="composer__well">
          <textarea id="question" ref={box} rows={1} value={question} placeholder="Ask about your notes…"
                    onChange={(e) => { setQuestion(e.target.value); grow(); }} onKeyDown={onKey} />
        </div>
        <Push variant="primary" type="submit" icon disabled={busy || !question.trim()} aria-label="Ask" title="Ask">
          <ArrowUp size={20} aria-hidden="true" />
        </Push>
      </form>
    </section>
  );
}
