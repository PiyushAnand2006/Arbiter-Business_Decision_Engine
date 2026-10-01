import React, { useEffect, useMemo, useRef, useState } from "react";
import { pct } from "../lib/format.js";

function useWidth(ref, fallback = 600) {
  const [w, setW] = useState(fallback);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(120, e.contentRect.width)));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, [ref]);
  return w;
}

/* ------------------------------------------------------------------ gate bar
   Part-to-whole of every fact: direct / conflict / stale. 2px surface gaps,
   legend doubles as the table view (value + share for every segment). */
export function GateBar({ segments }) {
  const total = segments.reduce((a, s) => a + s.value, 0) || 1;
  const [hover, setHover] = useState(null);
  const ref = useRef(null);
  return (
    <div className="chart" ref={ref}>
      <div className="gate" role="img" aria-label={segments.map((s) => `${s.label} ${s.value}`).join(", ")}>
        {segments.map((s, i) => (
          <div key={s.key} className="gate-seg" style={{ flexGrow: s.value || 0.0001, background: s.color }}
            onPointerEnter={(e) => {
              const r = e.currentTarget.getBoundingClientRect();
              const p = ref.current.getBoundingClientRect();
              setHover({ i, x: r.left - p.left + r.width / 2 });
            }}
            onPointerLeave={() => setHover(null)} />
        ))}
      </div>
      {hover && (
        <div className="tip" style={{ left: hover.x, top: 0 }}>
          <b>{segments[hover.i].value}</b> <span className="k">{segments[hover.i].label} · {pct(segments[hover.i].value / total, 1)}</span>
        </div>
      )}
      <div className="legend">
        {segments.map((s) => (
          <div key={s.key} className="legend-item">
            <span className="legend-key"><i className="sw" style={{ background: s.color }} />{s.label}</span>
            <span className="legend-val">{s.value}<small>{pct(s.value / total, s.value / total < 0.1 ? 1 : 0)}</small></span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ sparkline
   One series: de-emphasis line, current point in the accent, crosshair tooltip. */
export function Sparkline({ points, height = 34, format = (p) => p.value, color = "var(--s-conflict)" }) {
  const ref = useRef(null);
  const w = useWidth(ref, 160);
  const [hi, setHi] = useState(null);
  if (!points || points.length < 2)
    return <div ref={ref} style={{ height }} className="xs faint row">Collecting history…</div>;
  const vals = points.map((p) => p.value);
  const max = Math.max(...vals, 1);
  const min = Math.min(...vals, 0);
  const pad = 4;
  const x = (i) => pad + (i / (points.length - 1)) * (w - pad * 2);
  const y = (v) => pad + (1 - (v - min) / (max - min || 1)) * (height - pad * 2);
  const d = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ");
  const last = points.length - 1;
  const onMove = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    const i = Math.round(((e.clientX - r.left - pad) / (w - pad * 2)) * last);
    setHi(Math.max(0, Math.min(last, i)));
  };
  return (
    <div className="chart" ref={ref} style={{ height }}>
      <svg width={w} height={height} onPointerMove={onMove} onPointerLeave={() => setHi(null)} role="img"
        aria-label={`Trend, latest ${vals[last]}`}>
        <path d={d} fill="none" stroke="var(--text-3)" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
        {hi != null && <line x1={x(hi)} x2={x(hi)} y1={0} y2={height} stroke="var(--axis)" strokeWidth="1" />}
        <circle cx={x(hi ?? last)} cy={y(vals[hi ?? last])} r="4" fill={color} stroke="var(--panel)" strokeWidth="2" />
      </svg>
      {hi != null && (
        <div className="tip" style={{ left: x(hi), top: 0 }}>{format(points[hi])}</div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ decay chart
   Confidence of the weakest fact over time: C(t) = wF·F0·2^(-t/h) + wR·R + wA·A.
   Solid = since the last verification, dashed = projection. The threshold is the
   only reference line; crossing it is when the answer goes stale. */
export function DecayChart({ F, R, A, halfLife, weights, thresh, height = 150 }) {
  const ref = useRef(null);
  const w = useWidth(ref, 480);
  const [hi, setHi] = useState(null);
  const model = useMemo(() => {
    const sw = weights.F + weights.R + weights.A;
    const rest = (weights.R * R + weights.A * A) / sw;
    const wf = weights.F / sw;
    const age = F > 0 ? -halfLife * Math.log2(F) : halfLife * 8;
    const C = (t) => wf * Math.pow(2, -(age + t) / halfLife) + rest;
    const ratio = (thresh - rest) / wf;
    const cross = ratio <= 0 ? null : ratio >= 1 ? -age : -halfLife * Math.log2(ratio) - age;
    const x0 = -Math.min(age, 120);
    const x1 = cross != null && cross > 0 ? Math.min(Math.max(cross * 1.35, 14), 120) : Math.max(14, Math.min(age * 0.25, 45));
    const yMin = Math.max(0, Math.floor((Math.min(rest, thresh) - 0.08) * 10) / 10);
    return { C, cross, x0, x1, yMin, rest };
  }, [F, R, A, halfLife, weights, thresh]);

  const m = { l: 34, r: 14, t: 14, b: 22 };
  const iw = w - m.l - m.r;
  const ih = height - m.t - m.b;
  const X = (t) => m.l + ((t - model.x0) / (model.x1 - model.x0)) * iw;
  const Y = (c) => m.t + (1 - (c - model.yMin) / (1 - model.yMin)) * ih;
  const path = (a, b) => {
    const n = 60;
    let d = "";
    for (let i = 0; i <= n; i++) {
      const t = a + ((b - a) * i) / n;
      d += `${i ? "L" : "M"}${X(t).toFixed(1)},${Y(model.C(t)).toFixed(1)}`;
    }
    return d;
  };
  const cNow = model.C(0);
  const crossIn = model.cross != null && model.cross > model.x0 && model.cross < model.x1;
  const dayLabel = (t) => (Math.abs(t) < 0.5 ? "now" : t > 0 ? `in ${Math.round(t)}d` : `${Math.round(-t)}d ago`);
  const onMove = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    const t = model.x0 + ((e.clientX - r.left - m.l) / iw) * (model.x1 - model.x0);
    setHi(Math.max(model.x0, Math.min(model.x1, Math.round(t))));
  };
  // Keep axis labels from colliding: drop an end label that sits too close to "now".
  const ticks = [model.x0, 0, model.x1].filter((t, i, a) => a.indexOf(t) === i &&
    (t === 0 || Math.abs(X(t) - X(0)) > 56));

  return (
    <div className="chart" ref={ref}>
      <svg width={w} height={height} onPointerMove={onMove} onPointerLeave={() => setHi(null)} role="img"
        aria-label={`Confidence ${cNow.toFixed(2)} now, threshold ${thresh}`}>
        <rect x={m.l} y={Y(thresh)} width={iw} height={Math.max(0, Y(model.yMin) - Y(thresh))} fill="var(--critical-wash)" />
        {[model.yMin, 1].map((v) => (
          <g key={v}>
            <line className="gridline" x1={m.l} x2={m.l + iw} y1={Y(v)} y2={Y(v)} />
            <text className="axis-text" x={m.l - 8} y={Y(v) + 3.5} textAnchor="end">{v.toFixed(1)}</text>
          </g>
        ))}
        <line x1={m.l} x2={m.l + iw} y1={Y(thresh)} y2={Y(thresh)} stroke="var(--critical)" strokeWidth="1" strokeDasharray="3 3" />
        <text className="ref-text" x={m.l + iw} y={Y(thresh) - 5} textAnchor="end">Threshold {thresh.toFixed(2)}</text>
        {ticks.map((t) => (
          <text key={t} className="axis-text" x={X(t)} y={height - 5}
            textAnchor={t === model.x0 ? "start" : t === model.x1 ? "end" : "middle"}>{dayLabel(t)}</text>
        ))}
        <path d={path(model.x0, 0)} fill="none" stroke="var(--s-direct)" strokeWidth="2" strokeLinecap="round" />
        <path d={path(0, model.x1)} fill="none" stroke="var(--s-direct)" strokeWidth="2" strokeDasharray="4 4" opacity="0.7" />
        {crossIn && model.cross > 0 && (
          <g>
            <line x1={X(model.cross)} x2={X(model.cross)} y1={m.t} y2={m.t + ih} stroke="var(--axis)" strokeWidth="1" />
            <circle cx={X(model.cross)} cy={Y(thresh)} r="3.5" fill="var(--critical)" stroke="var(--panel)" strokeWidth="2" />
          </g>
        )}
        {hi != null && <line x1={X(hi)} x2={X(hi)} y1={m.t} y2={m.t + ih} stroke="var(--axis)" strokeWidth="1" />}
        <circle cx={X(0)} cy={Y(cNow)} r="4.5" fill="var(--s-direct)" stroke="var(--panel)" strokeWidth="2" />
        {hi != null && <circle cx={X(hi)} cy={Y(model.C(hi))} r="4" fill="var(--s-direct)" stroke="var(--panel)" strokeWidth="2" />}
      </svg>
      {hi != null && (
        <div className="tip" style={{ left: X(hi), top: Y(model.C(hi)) }}>
          <b>{model.C(hi).toFixed(2)}</b><span className="k">{dayLabel(hi)}</span>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ bar list
   Single series, one color, value at the tip. `emphasis` highlights one bar and grays the rest. */
export function BarList({ items, max, format = (v) => v, color = "var(--s-direct)" }) {
  const top = max ?? Math.max(1, ...items.map((i) => i.value));
  return (
    <div>
      {items.map((it) => (
        <div className="hbar" key={it.label} title={`${it.label}: ${format(it.value)}`}>
          <span className="truncate muted">{it.label}</span>
          <span className="hbar-track">
            <span className="hbar-fill" style={{ display: "block", width: `${(it.value / top) * 100}%`,
              background: it.emphasis === false ? "var(--text-3)" : it.color || color }} />
          </span>
          <span className="v">{format(it.value)}</span>
        </div>
      ))}
    </div>
  );
}
