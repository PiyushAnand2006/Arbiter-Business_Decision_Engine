import React, { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "motion/react";
import { ArrowRight, LoaderCircle, Search, X } from "lucide-react";
import { EASE, Meter, Page, ReasonBadge, Segmented, StatusBadge } from "../components/ui.jsx";
import { api } from "../lib/api.js";
import { FIELD, SOURCE, SOURCES, ago } from "../lib/format.js";
import { navigate } from "../lib/router.js";
import { useArbiter } from "../lib/store.jsx";

const ROWS = [
  ["company", "Company"], ["stage", "Stage"], ["value", "Value"], ["close_date", "Close date"],
  ["owner", "Owner"], ["last_contacted", "Last contacted"], ["invoice_status", "Invoice status"], ["forecast_category", "Forecast"],
];

function SystemDots({ deal }) {
  return (
    <span className="row" style={{ gap: 4 }} aria-label="Agreement by system">
      {SOURCES.map((s) => {
        const out = deal.outliers?.includes(s);
        const stale = deal.status === "stale";
        const color = out ? "var(--s-conflict)" : stale ? "var(--s-stale)" : "var(--line-2)";
        return (
          <span key={s} title={`${SOURCE[s]}: ${out ? "disagrees" : stale ? "stale" : "agrees"}`}
            className="xs" style={{ display: "inline-flex", alignItems: "center", gap: 3, color: out ? "var(--text)" : "var(--text-3)" }}>
            <span className="dot" style={{ background: color, width: 8, height: 8 }} />{SOURCE[s].slice(0, 3)}
          </span>
        );
      })}
    </span>
  );
}

function EditCell({ value, onSave, diff }) {
  const [editing, setEditing] = useState(false);
  const [v, setV] = useState(value ?? "");
  const [saved, setSaved] = useState(false);
  useEffect(() => setV(value ?? ""), [value]);
  if (editing)
    return (
      <input className="input" style={{ height: 28, fontSize: 12.5 }} autoFocus value={v} onChange={(e) => setV(e.target.value)}
        onBlur={() => setEditing(false)}
        onKeyDown={async (e) => {
          if (e.key === "Escape") { setV(value ?? ""); setEditing(false); }
          if (e.key === "Enter") {
            setEditing(false);
            if (v !== value && (await onSave(v))) { setSaved(true); setTimeout(() => setSaved(false), 1800); }
          }
        }} />
    );
  return (
    <button className={`edit-cell ${saved ? "saved" : ""}`} onClick={() => setEditing(true)} title="Click to edit"
      style={diff ? { color: "var(--text)", boxShadow: "inset 2px 0 0 var(--s-conflict)" } : undefined}>
      {value ?? <span className="faint">—</span>}
    </button>
  );
}

function RecordDrawer({ dealId, onClose }) {
  const { actor, run, tick } = useArbiter();
  const [d, setD] = useState(null);
  const load = () => api.deal(dealId).then(setD).catch(() => setD(false));
  useEffect(() => { setD(null); load(); }, [dealId]);
  useEffect(() => { if (d) load(); }, [Math.floor(tick / 2)]);

  const save = async (source, field, value) => {
    const r = await run(() => api.editSource(source, dealId, { field, value, actor: actor || "presenter" }), {
      success: { title: `Saved to ${SOURCE[source]}`, description: "The monitor will re-check this deal within seconds." },
      error: "Edit rejected",
    });
    if (r) load();
    return !!r;
  };
  const facts = d ? Object.fromEntries(d.facts.map((f) => [f.field, f])) : {};
  const outlier = (field, source) => {
    const f = facts[field];
    return f?.reason === "conflict" && f.groups?.length && !f.groups[0].sources.includes(source);
  };

  return (
    <>
      <motion.div className="scrim" onClick={onClose} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }} />
      <motion.aside className="drawer" role="dialog" aria-label={`Record ${dealId}`}
        initial={{ x: "100%" }} animate={{ x: 0 }} exit={{ x: "100%" }} transition={{ duration: 0.32, ease: EASE }}>
        <div className="drawer-head">
          <div className="col grow">
            <span className="row"><span className="mono strong" style={{ fontSize: 15 }}>{dealId}</span>{d && <span className="muted truncate">{d.company}</span>}</span>
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Close"><X size={16} /></button>
        </div>
        <div className="drawer-body">
          {d === null && <div className="placeholder" style={{ height: 200 }}><LoaderCircle size={18} className="spin" /></div>}
          {d === false && <div className="placeholder" style={{ height: 200 }}>Deal not found.</div>}
          {d && (
            <>
              <div className="dv-section">
                <span className="label">Golden record</span>
                <div className="res">
                  {d.facts.map((f) => (
                    <div className="res-row" key={f.field} style={{ gridTemplateColumns: "96px 1fr auto", padding: "11px 14px" }}>
                      <span className="res-field">{FIELD[f.field]}</span>
                      <span className="strong truncate">{f.groups[0]?.display ?? "—"}</span>
                      <span className="row" style={{ gap: 10 }}>
                        {f.reason !== "clean" && <ReasonBadge reason={f.reason} />}
                        <Meter value={f.confidence} thresh={0.6} width={48} />
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="dv-section">
                <div className="row" style={{ marginBottom: 10 }}>
                  <span className="label grow">By system</span>
                  <span className="xs faint">Click a value to edit it</span>
                </div>
                <div className="box" style={{ padding: 0 }}>
                  <div className="table-wrap">
                    <table className="table">
                      <thead><tr><th />{SOURCES.map((s) => <th key={s}>{SOURCE[s]}</th>)}</tr></thead>
                      <tbody>
                        {ROWS.filter(([k]) => SOURCES.some((s) => d.rows[s] && k in d.rows[s])).map(([k, label]) => (
                          <tr key={k}>
                            <td className="small faint" style={{ whiteSpace: "nowrap" }}>{label}</td>
                            {SOURCES.map((s) => (
                              <td key={s} className="small">
                                {d.rows[s] && k in d.rows[s]
                                  ? <EditCell value={d.rows[s][k]} diff={outlier(k, s)} onSave={(v) => save(s, k, v)} />
                                  : <span className="faint">—</span>}
                              </td>
                            ))}
                          </tr>
                        ))}
                        <tr>
                          <td className="small faint">Updated</td>
                          {SOURCES.map((s) => <td key={s} className="small muted">{d.rows[s] ? ago(d.rows[s].updated_at) : "—"}</td>)}
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>

              {d.decisions.length > 0 && (
                <div className="dv-section">
                  <span className="label">Decisions</span>
                  <div className="box" style={{ padding: 0 }}>
                    <ul className="list">
                      {d.decisions.map((c) => (
                        <li key={c.id}>
                          <button className="list-row" onClick={() => navigate("review", c.id)}>
                            <span className="xs faint num">#{c.id}</span>
                            <span className="grow truncate">{c.fields.map((f) => FIELD[f] || f).join(", ")}</span>
                            <StatusBadge status={c.status} size={13} />
                            <ArrowRight size={13} color="var(--text-3)" />
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              )}

              <div className="dv-section">
                <span className="label">Audit log</span>
                <ul className="timeline">
                  {d.audit.slice(0, 14).map((a) => (
                    <li key={a.id}>
                      <span className="tl-icon" style={{ fontSize: 8, fontWeight: 700 }}>{SOURCE[a.source]?.[0]}</span>
                      <div className="row"><span className="tl-title grow">{SOURCE[a.source]} · {FIELD[a.field] || a.field.replace("_", " ")}</span><span className="tl-time">{ago(a.changed_at)}</span></div>
                      <div className="tl-detail">{a.old_value ?? "—"} → {a.new_value} · {a.changed_by} <span className="faint">({a.reason})</span></div>
                    </li>
                  ))}
                </ul>
              </div>
            </>
          )}
        </div>
      </motion.aside>
    </>
  );
}

export default function Records({ id }) {
  const { tick } = useArbiter();
  const [deals, setDeals] = useState(null);
  const [filter, setFilter] = useState("all");
  const [q, setQ] = useState("");
  useEffect(() => { api.deals().then(setDeals).catch(() => {}); }, [Math.floor(tick / 2)]);

  const counts = useMemo(() => {
    const c = { all: 0, conflict: 0, stale: 0, clean: 0 };
    (deals || []).forEach((d) => { c.all++; c[d.status]++; });
    return c;
  }, [deals]);
  const rows = useMemo(() => {
    const term = q.trim().toLowerCase();
    return (deals || []).filter((d) => (filter === "all" || d.status === filter) &&
      (!term || `${d.deal_id} ${d.company} ${d.owner}`.toLowerCase().includes(term)));
  }, [deals, filter, q]);

  return (
    <Page>
      <div className="page-head">
        <div>
          <h1 className="page-title">Records</h1>
          <div className="page-sub">The golden record for every deal, reconciled across CRM, Finance and Pipeline.</div>
        </div>
      </div>
      <div className="row wrap" style={{ marginBottom: 12, gap: 10 }}>
        <Segmented label="Record filter" value={filter} onChange={setFilter} options={[
          { value: "all", label: "All", count: counts.all }, { value: "conflict", label: "Conflicts", count: counts.conflict },
          { value: "stale", label: "Stale", count: counts.stale }, { value: "clean", label: "Clean", count: counts.clean },
        ]} />
        <span className="grow" />
        <div className="search" style={{ width: 260 }}>
          <Search size={14} />
          <input className="input" placeholder="Search deals, companies, owners" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
      </div>
      <section className="card" style={{ overflow: "hidden" }}>
        <div className="table-wrap">
          <table className="table hover">
            <thead>
              <tr>
                <th>Deal</th><th>Stage</th><th className="num">Value</th><th>Close date</th>
                <th>Systems</th><th>Confidence</th><th>Status</th>
              </tr>
            </thead>
            <tbody>
              {deals == null && <tr><td colSpan={7} className="faint">Loading…</td></tr>}
              {rows.map((d) => (
                <tr key={d.deal_id} className={id === d.deal_id ? "sel" : ""} onClick={() => navigate("records", d.deal_id)}>
                  <td><div className="mono strong">{d.deal_id}</div><div className="cell-sub truncate" style={{ maxWidth: 220 }}>{d.company}</div></td>
                  <td>{d.facts.stage?.display}</td>
                  <td className="num">{d.facts.value?.display}</td>
                  <td className="num">{d.facts.close_date?.display}</td>
                  <td><SystemDots deal={d} /></td>
                  <td><Meter value={d.min_confidence} thresh={0.6} /></td>
                  <td>{d.status === "clean" ? <span className="xs faint">Clean</span> : <ReasonBadge reason={d.status} />}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      {createPortal(<AnimatePresence>{id && <RecordDrawer key={id} dealId={id} onClose={() => navigate("records")} />}</AnimatePresence>, document.body)}
    </Page>
  );
}
