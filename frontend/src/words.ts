import type { FormatType, Label } from "./types";

export const REL: Record<Label, { title: string; why: string }> = {
  Certain: { title: "I'm sure about this", why: "It's written clearly in your notes." },
  Moderate: { title: "I think so", why: "I found it, though the wording was a little loose or a few words were hard to make out." },
  Uncertain: { title: "I'm not certain", why: "I couldn't find solid support for this, so it's worth checking the source." },
  Unreadable: { title: "I couldn't read that part", why: "The bit with the answer was too hard to read (a faint scan or messy handwriting)." },
};

export const FORMAT: Record<FormatType, string> = { typed: "Typed", scanned: "Printed / scanned", handwritten: "Handwritten" };

/** Same text as NOT_FOUND_ANSWER in app/modules/llm_answer.py. */
export const NOT_FOUND = "I couldn't find the answer to that in the uploaded documents.";

export const SUGGESTIONS = ["What's this document about?", "Sum up the key points", "What are the main topics?", "Explain the first idea simply"];
export const STEPS = ["Uploading", "Looking at your pages", "Reading the text", "Making sense of it", "Nearly there"];

// Same cut-offs as the reliability labels (app/modules/reliability.py).
export type Tone = "high" | "mid" | "low";
export const confTone = (c: number): Tone => (c >= 0.9 ? "high" : c >= 0.6 ? "mid" : "low");
export const CONF_WORD: Record<Tone, string> = { high: "clear", mid: "partly legible", low: "hard to read" };
export const matchTone = (s: number): Tone => (s >= 0.7 ? "high" : s >= 0.6 ? "mid" : "low");
export const MATCH_WORD: Record<Tone, string> = { high: "strong", mid: "fair", low: "weak" };

/** Rounded down, so a percentage never crosses a cut-off its colour has not (0.698 is 69%, not 70%). */
export const pct = (v: number) => `${Math.floor(v * 100)}%`;

// Layout regions found on scanned / handwritten pages (layout_analysis.py).
export const REGION: Record<string, [string, string]> = {
  title: ["Title", "titles"], text: ["Text", "text blocks"], table: ["Table", "tables"], figure: ["Figure", "figures"],
  caption: ["Caption", "captions"], formula: ["Formula", "formulas"], header: ["Header", "headers"],
  footer: ["Footer", "footers"], reference: ["Reference", "references"],
};
export const BLOCK: Record<string, [string, string]> = { paragraph: ["Paragraph", "paragraphs"], table: ["Table", "tables"], image: ["Picture", "pictures"] };

export const plural = (n: number, [one, many]: [string, string]) => `${n} ${n === 1 ? one.toLowerCase() : many}`;
