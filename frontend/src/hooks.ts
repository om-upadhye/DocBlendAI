import { useCallback, useEffect, useLayoutEffect, useState, useSyncExternalStore, type CSSProperties, type RefObject } from "react";

export function useMedia(query: string): boolean {
  const [matches, setMatches] = useState(() => matchMedia(query).matches);
  useEffect(() => {
    const m = matchMedia(query);
    const on = () => setMatches(m.matches);
    on();
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, [query]);
  return matches;
}

/** Phones, small tablets and landscape phones: one panel at a time with tabs at the bottom. */
export const PHONE = "(max-width: 920px), (max-height: 520px) and (pointer: coarse)";
export const useIsPhone = () => useMedia(PHONE);
export const useTouch = () => useMedia("(pointer: coarse)");
export const reducedMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Position of the raised key in a tray: it slides under whichever option has .is-on. */
export function useSlider(tray: RefObject<HTMLElement | null>, active: string): CSSProperties {
  const [style, setStyle] = useState<CSSProperties>({ opacity: 0 });
  useLayoutEffect(() => {
    const box = tray.current;
    if (!box) return;
    const place = () => {
      const on = box.querySelector<HTMLElement>(".is-on");
      if (!on) { setStyle({ opacity: 0 }); return; }
      setStyle({ width: on.offsetWidth, height: on.offsetHeight, transform: `translate(${on.offsetLeft}px, ${on.offsetTop}px)` });
    };
    place();
    const watch = new ResizeObserver(place);
    watch.observe(box);
    return () => watch.disconnect();
  }, [tray, active]);
  return style;
}

// ---------- theme: porcelain or graphite ----------

export type Theme = "dark" | "light";
const THEME_COLOR: Record<Theme, string> = { dark: "#191d1f", light: "#eef1f0" };
const readTheme = (): Theme => (document.documentElement.dataset.theme === "dark" ? "dark" : "light");

function subscribe(onChange: () => void) {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  return () => observer.disconnect();
}

function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", THEME_COLOR[theme]);
  try { localStorage.setItem("theme", theme); } catch { /* the choice just won't be remembered */ }
}

/** The new theme spreads out as a circle from the switch; colours cross-fade where that is not supported. */
function transitionTheme(next: Theme, x: number, y: number) {
  const root = document.documentElement;
  if (reducedMotion()) return applyTheme(next);
  if (!document.startViewTransition) {
    root.classList.add("theme-fading");
    applyTheme(next);
    setTimeout(() => root.classList.remove("theme-fading"), 650);
    return;
  }
  const radius = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
  document.startViewTransition(() => applyTheme(next)).ready.then(() => {
    root.animate(
      { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${radius}px at ${x}px ${y}px)`] },
      { duration: 800, easing: "cubic-bezier(0.65, 0, 0.35, 1)", pseudoElement: "::view-transition-new(root)" },
    );
  }).catch(() => { /* skipped: the theme is still applied */ });
}

export function useTheme() {
  const theme = useSyncExternalStore(subscribe, readTheme, () => "light" as Theme);
  const toggle = useCallback((x: number, y: number) => transitionTheme(readTheme() === "dark" ? "light" : "dark", x, y), []);
  return { theme, toggle };
}
