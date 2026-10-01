import React, { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, animate, motion } from "motion/react";
import {
  CircleCheck, CircleDot, CircleX, LoaderCircle, Minus, TriangleAlert, Check,
} from "lucide-react";

export const EASE = [0.2, 0, 0, 1];

/* -------------------------------------------------------------- status */
const STATUS = {
  debating: { label: "Debating", Icon: LoaderCircle, color: "var(--text-2)", spin: true },
  pending_approval: { label: "Awaiting approval", Icon: CircleDot, color: "var(--warning)" },
  needs_review: { label: "Needs review", Icon: TriangleAlert, color: "var(--critical)" },
  approved: { label: "Approved", Icon: CircleCheck, color: "var(--good)" },
  rejected: { label: "Rejected", Icon: CircleX, color: "var(--text-3)" },
  superseded: { label: "Superseded", Icon: Minus, color: "var(--text-3)" },
  informational: { label: "Answered", Icon: Check, color: "var(--s-direct)" },
};
const STAGE = { arguing: "Arguing", judging: "Judging", verifying: "Verifying" };

export function StatusBadge({ status, progress, size = 14 }) {
  const s = STATUS[status] || { label: status, Icon: CircleDot, color: "var(--text-3)" };
  const label = status === "debating" && progress?.stage ? STAGE[progress.stage] || s.label : s.label;
  return (
    <span className="status">
      <s.Icon size={size} color={s.color} className={s.spin ? "spin" : undefined} aria-hidden />
      {label}
    </span>
  );
}

export function Severity({ level }) {
  if (!level) return null;
  return (
    <span className={`sev ${level}`} title={`${level} severity`}>
      <span className="sev-bars" aria-hidden><i /><i /><i /></span>
      {level[0].toUpperCase() + level.slice(1)}
    </span>
  );
}

const KIND_COLOR = { stale_record: "var(--s-stale)" };
export function Discrepancy({ d }) {
  return (
    <span className="badge" title={d.detail}>
      <span className="sw" style={{ background: KIND_COLOR[d.type] || "var(--s-conflict)" }} />
      {d.label}
    </span>
  );
}

export function ReasonBadge({ reason, path }) {
  if (path === "direct" || reason === "clean")
    return <span className="badge"><span className="sw" style={{ background: "var(--s-direct)" }} />Direct</span>;
  if (path === "provisional")
    return <span className="badge outline">Provisional</span>;
  return (
    <span className="badge">
      <span className="sw" style={{ background: reason === "stale" ? "var(--s-stale)" : "var(--s-conflict)" }} />
      {reason === "stale" ? "Stale" : "Conflict"}
    </span>
  );
}

/* -------------------------------------------------------------- controls */
export function Kbd({ children }) {
  return <kbd className="kbd">{children}</kbd>;
}

export function Segmented({ value, onChange, options, label }) {
  const id = useId();
  return (
    <div className="seg" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} role="radio" aria-checked={value === o.value} className={value === o.value ? "on" : ""}
          onClick={() => onChange(o.value)}>
          {value === o.value && (
            <motion.span layoutId={`seg-${id}`} className="seg-thumb" transition={{ duration: 0.22, ease: EASE }} />
          )}
          {o.label}
          {o.count != null && <span className="n">{o.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Tabs({ value, onChange, tabs }) {
  const id = useId();
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t.value} role="tab" aria-selected={value === t.value} className={`tab ${value === t.value ? "on" : ""}`}
          onClick={() => onChange(t.value)}>
          {t.label}
          {t.count != null && <span className="n">{t.count}</span>}
          {value === t.value && <motion.span layoutId={`tab-${id}`} className="tab-line" transition={{ duration: 0.25, ease: EASE }} />}
        </button>
      ))}
    </div>
  );
}

export function Switch({ on, onChange, label }) {
  return <button className={`switch ${on ? "on" : ""}`} role="switch" aria-checked={on} aria-label={label} onClick={() => onChange(!on)} />;
}

export function Meter({ value, thresh, color, width, hideValue = false }) {
  const v = Math.max(0, Math.min(1, value ?? 0));
  const fill = color || (thresh != null && v < thresh ? "var(--critical)" : "var(--s-direct)");
  return (
    <span className="meter">
      <span className="meter-track" style={width ? { width } : undefined}>
        <span className="meter-fill" style={{ width: `${v * 100}%`, background: fill }} />
      </span>
      {!hideValue && <span className="meter-val">{value == null ? "—" : v.toFixed(2)}</span>}
    </span>
  );
}

/** Animates between values instead of snapping (respects reduced motion via MotionConfig). */
export function AnimatedNumber({ value, format = (v) => Math.round(v).toLocaleString("en-US") }) {
  const ref = useRef(null);
  const prev = useRef(value);
  useEffect(() => {
    const from = prev.current ?? 0;
    prev.current = value;
    if (value == null || !ref.current) return;
    const ctl = animate(from, value, {
      duration: 0.6, ease: EASE,
      onUpdate: (v) => { if (ref.current) ref.current.textContent = format(v); },
    });
    return () => ctl.stop();
  }, [value]);
  return <span ref={ref}>{value == null ? "—" : format(value)}</span>;
}

export function EvidenceId({ id, hl, onHover }) {
  return (
    <button type="button" className={`eid ${hl === id ? "hl" : ""}`} onMouseEnter={() => onHover?.(id)}
      onMouseLeave={() => onHover?.(null)} onFocus={() => onHover?.(id)} onBlur={() => onHover?.(null)}
      title="Evidence ID">
      {id}
    </button>
  );
}

export function Card({ title, meta, actions, children, className = "", bodyClass = "card-body", foot }) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="card-head">
          <h3 className="card-title">{title}</h3>
          {meta && <span className="card-meta">{meta}</span>}
          {actions && <span style={{ marginLeft: "auto" }} className="row">{actions}</span>}
        </header>
      )}
      <div className={bodyClass}>{children}</div>
      {foot && <footer className="card-foot">{foot}</footer>}
    </section>
  );
}

/* -------------------------------------------------------------- popover */
export function Popover({ open, onClose, anchorRef, children, align = "right", width }) {
  const ref = useRef(null);
  const [pos, setPos] = useState(null);
  useLayoutEffect(() => {
    if (!open || !anchorRef.current) return;
    const r = anchorRef.current.getBoundingClientRect();
    setPos({ top: r.bottom + 6, ...(align === "right" ? { right: Math.max(8, window.innerWidth - r.right) } : { left: r.left }) });
  }, [open, anchorRef, align]);
  useEffect(() => {
    if (!open) return;
    const onDown = (e) => {
      if (!ref.current?.contains(e.target) && !anchorRef.current?.contains(e.target)) onClose();
    };
    const onKey = (e) => e.key === "Escape" && onClose();
    document.addEventListener("pointerdown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, onClose, anchorRef]);
  return createPortal(
    <AnimatePresence>
      {open && pos && (
        <motion.div ref={ref} className="popover" role="dialog" style={{ position: "fixed", ...pos, width }}
          initial={{ opacity: 0, scale: 0.97, y: -4 }} animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.98, y: -2 }} transition={{ duration: 0.16, ease: EASE }}>
          {children}
        </motion.div>
      )}
    </AnimatePresence>,
    document.body
  );
}

/** Page-level enter transition. */
export function Page({ children, className = "page" }) {
  return (
    <motion.div className={className} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: EASE }}>
      {children}
    </motion.div>
  );
}
