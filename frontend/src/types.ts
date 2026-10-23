export type FormatType = "typed" | "scanned" | "handwritten";
export type Label = "Certain" | "Moderate" | "Uncertain" | "Unreadable";
export type ContentType = "paragraph" | "table" | "image";

export interface Doc {
  doc_id: string;
  file_path: string;
  format_type: FormatType;
  page_count: number;
}

export interface Line {
  text: string;
  conf: number;
  box: number[];
}

export interface Region {
  type: string;
  box: number[];
  text: string;
  conf: number;
  rows?: string[][] | null;
}

export interface Block {
  type: ContentType;
  text: string;
  box: number[] | null;
  rows?: string[][] | null;
  picture_url?: string | null;
}

export interface Page {
  page: number;
  text: string;
  conf: number;
  image_url: string | null;
  lines: Line[];
  regions: Region[];
  blocks: Block[];
  layout_text: string;
}

export interface Answer {
  answer_id: string;
  answer_text: string;
  reliability_label: Label;
}

export interface Source {
  chunk_id: string;
  doc_id: string;
  content_type: ContentType;
  text: string;
  similarity: number;
  confidence: number;
  combined_score: number;
}

/** Pages shown in the preview and the floating window ("Slide" for PowerPoint). */
export interface PageSet {
  docId: string;
  name: string;
  pages: Pick<Page, "page" | "image_url" | "text">[];
  word: string;
}
