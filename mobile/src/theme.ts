// Same palette as the website (app/static/index.html).
export const colors = {
  bg: '#f5f7fb',
  panel: '#ffffff',
  text: '#1f2a44',
  muted: '#6b7690',
  line: '#e6eaf2',
  soft: '#eef2fb',
  accent: '#4f6ef7',
  accent2: '#7c93ff',
  accentSoft: '#eaeefe',
  mint: '#13805f',
  mintSoft: '#e5f7f0',
  amber: '#9a6300',
  amberSoft: '#fdf3dd',
  violet: '#7d5bd6',
  violetSoft: '#f0ebfc',
  rose: '#e0554d',
  roseSoft: '#fdeceb',
};

export type Reliability = 'Certain' | 'Moderate' | 'Uncertain' | 'Unreadable';

export const RELIABILITY: Record<Reliability, {icon: string; title: string; why: string; fg: string; bg: string}> = {
  Certain: {icon: '✔', title: "I'm confident", why: 'This is clearly written in your document.', fg: colors.mint, bg: colors.mintSoft},
  Moderate: {icon: '◐', title: 'Fairly sure', why: 'I found it, but the match was a bit loose or some words were hard to read.', fg: colors.amber, bg: colors.amberSoft},
  Uncertain: {icon: '?', title: 'Not sure', why: "I couldn't find strong support for this. Please check the source.", fg: colors.violet, bg: colors.violetSoft},
  Unreadable: {icon: '!', title: "Couldn't read it", why: 'The part that answers this was too hard to read (poor scan or handwriting).', fg: colors.rose, bg: colors.roseSoft},
};

export const FORMAT_LABEL: Record<string, string> = {
  typed: 'Typed',
  scanned: 'Printed / scanned',
  handwritten: 'Handwritten',
};

// Same cut-offs as the reliability labels.
export function confColor(conf: number): string {
  return conf >= 0.85 ? colors.mint : conf >= 0.6 ? colors.amber : colors.rose;
}
