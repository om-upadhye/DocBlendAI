import { useRef, type ButtonHTMLAttributes, type MouseEvent, type ReactNode } from "react";
import { useSlider, useTheme } from "../hooks";

type PushProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "key";
  size?: "sm" | "md";
  icon?: boolean;
  children: ReactNode;
};

/** A physical, pushable key: it lifts on hover and presses down onto its edge on click. */
export function Push({ variant = "key", size = "md", icon = false, className = "", children, ...rest }: PushProps) {
  const cls = ["push", `push--${variant}`, size === "sm" && "push--sm", icon && "push--icon", className].filter(Boolean).join(" ");
  return (
    <button type="button" {...rest} className={cls}>
      <span aria-hidden="true" className="push__shadow" />
      <span aria-hidden="true" className="push__edge" />
      <span className="push__front">{children}</span>
    </button>
  );
}

/** Round, raised metal knob for icon actions (view, remove, close). */
export function Knob({ className = "", children, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { children: ReactNode }) {
  return <button type="button" {...rest} className={`knob ${className}`}>{children}</button>;
}

/** A recessed tray of keys where one is pressed in: a segmented control. The raised key slides between options. */
export function Tray<T extends string>({ options, value, onChange, label, small = false }: {
  options: [T, string][];
  value: T;
  onChange: (value: T) => void;
  label: string;
  small?: boolean;
}) {
  const box = useRef<HTMLDivElement>(null);
  const slide = useSlider(box, value);
  return (
    <div ref={box} className={`tray${small ? " tray--sm" : ""}`} role="radiogroup" aria-label={label}>
      <span aria-hidden="true" className="tray__key" style={slide} />
      {options.map(([v, text]) => {
        const on = v === value;
        return (
          <button key={v} type="button" role="radio" aria-checked={on} className={`tray__opt${on ? " is-on" : ""}`} onClick={() => onChange(v)}>
            <span className="tray__text">{text}</span>
          </button>
        );
      })}
    </div>
  );
}

/** Small skeuomorphic switch with an indicator light, for "Ask about this". */
export function Switch({ on, onChange, children }: { on: boolean; onChange: (on: boolean) => void; children: ReactNode }) {
  return (
    <button type="button" role="switch" aria-checked={on} className={`mini-switch${on ? " is-on" : ""}`} onClick={() => onChange(!on)}>
      <span aria-hidden="true" className="mini-switch__track"><span className="mini-switch__knob" /></span>
      <span className={`led${on ? " is-on" : ""}`} aria-hidden="true" />
      <span>{children}</span>
    </button>
  );
}

/** Day / warm-ash switch: a recessed track with a raised knob and an engraved sun or moon. */
export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const dark = theme === "dark";
  const onClick = (e: MouseEvent<HTMLButtonElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    toggle(r.left + r.width / 2, r.top + r.height / 2);
  };
  return (
    <button type="button" role="switch" aria-checked={dark} aria-label="Dark theme" title={dark ? "Switch to day theme" : "Switch to dark theme"}
            onClick={onClick} className="skeu-switch" data-on={dark || undefined}>
      <span aria-hidden="true" className="skeu-switch__track" />
      <span aria-hidden="true" className="skeu-switch__knob">
        <svg viewBox="0 0 24 24" className="skeu-switch__icon skeu-switch__icon--sun">
          <circle cx="12" cy="12" r="4.2" />
          <path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M5.3 18.7l1.6-1.6M17.1 6.9l1.6-1.6" />
        </svg>
        <svg viewBox="0 0 24 24" className="skeu-switch__icon skeu-switch__icon--moon">
          <path d="M19.5 14.6A7.8 7.8 0 0 1 9.4 4.5a7.8 7.8 0 1 0 10.1 10.1z" />
        </svg>
      </span>
    </button>
  );
}
