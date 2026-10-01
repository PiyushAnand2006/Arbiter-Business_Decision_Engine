import React, { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import {
  Check, ChevronDown, ChevronUp, CircleCheck, Clock, Database, Download, LoaderCircle, ShieldCheck,
  TriangleAlert, X, Split, ArrowLeft,
} from "lucide-react";
import { DecayChart } from "../components/charts.jsx";
import { IdentityPopover } from "../components/Shell.jsx";
import {
  Discrepancy, EASE, EvidenceId, Kbd, Meter, ReasonBadge, Segmented, Severity, StatusBadge, Tabs,
} from "../components/ui.jsx";
import { api } from "../lib/api.js";
import { APPROVABLE, FIELD, SOURCE, ago, duration, initials, money, pct, until } from "../lib/format.js";
import { navigate } from "../lib/router.js";
import { useArbiter } from "../lib/store.jsx";

const fade = { initial: { opacity: 0, y: 4 }, animate: { opacity: 1, y: 0 }, exit: { opacity: 0, y: -4 },
  transition: { duration: 0.18, ease: EASE } };

/* ================================================================== summary */
function Resolution({ card }) {
  const debating = card.status === "debating";
  const rejected = {};
  (card.counterfactuals || []).forEach((c) => { (rejected[c.field] ||= []).push(c); });
  const stale = card.reason === "stale";
  const staleVerdict = stale && card.debates?.[0]?.verdict?.winner;
  return (
    <div className="res">
      {stale && !debating && (
        <div className="res-row" style={{ gridTemplateColumns: "110px 1fr" }}>
          <span className="res-field">Recommendation</span>
          <span className="res-value" style={{ fontSize: 16 }}>
            {staleVerdict === "A" ? "Record still holds" : "Re-verify with the account owner before acting"}
          </span>
        </div>
      )}
      {card.facts.map((f) => {
        const answer = card.answer?.[f.field];
        const chosen = answer?.replace(" (re-verify)", "");
        const cf = rejected[f.field] || [];
        return (
          <div className="res-row" key={f.field}>
            <span className="res-field">{FIELD[f.field] || f.field}</span>
            <div className="col">
              {debating ? <span className="res-value pending">Debating…</span>
                : answer == null ? <span className="res-value bad">Unresolved - needs a person</span>
                : <span className="res-value">{chosen}</span>}
              {cf.filter((c) => c.rejected_value).map((c, i) => (
                <span className="res-was" key={i}>
                  Rejected <s>{c.rejected_value}</s> from {c.rejected_sources.map((s) => SOURCE[s]).join(", ")}
                </span>
              ))}
              {stale && <span className="res-was">Confidence {f.confidence.toFixed(2)} · last confirmed {Math.round(Math.min(...f.readings.map((r) => r.age_days)))} days ago</span>}
            </div>
            <div className="sys-strip">
              {f.readings.map((r) => {
                const win = f.groups.find((g) => g.display === chosen);
                const agrees = f.reason !== "conflict" || !win || win.sources.includes(r.source);
                const state = debating ? "neutral" : f.reason === "stale" ? "stale" : agrees ? "agree" : "differ";
                return (
                  <span key={r.source} className={`sys-chip ${state}`} title={`${SOURCE[r.source]}: ${r.raw} · updated ${r.age_days.toFixed(0)}d ago`}>
                    {state === "agree" ? <Check size={12} /> : state === "differ" ? <X size={12} />
                      : state === "stale" ? <Clock size={12} color="var(--s-stale)" /> : null}
                    <b>{SOURCE[r.source]}</b>
                    <span className="truncate" style={{ maxWidth: 110 }}>{r.raw}</span>
                  </span>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ConfidenceBox({ card, config }) {
  const thresh = config?.thresh_low ?? 0.6;
  const W = config?.weights || { F: 0.5, R: 0.15, A: 0.35 };
  const bd = card.confidence_breakdown || {};
  const field = card.confidence_field || card.fields[0];
  const hl = config?.half_life_days?.[field] ?? 30;
  const below = card.confidence < thresh;
  return (
    <div className="box">
      <div className="row">
        <span className="label grow">Objective confidence</span>
        <span className="xs faint">weakest fact · {FIELD[field] || field}</span>
      </div>
      <div className="row" style={{ alignItems: "baseline", gap: 10, marginTop: 6 }}>
        <span className="big-num">{card.confidence.toFixed(2)}</span>
        <span className="status">
          {below ? <TriangleAlert size={14} color="var(--critical)" /> : <CircleCheck size={14} color="var(--good)" />}
          {below ? `Below threshold ${thresh.toFixed(2)}` : `Above threshold ${thresh.toFixed(2)}`}
        </span>
      </div>
      <div className="fra">
        {[["Freshness", bd.F], ["Reliability", bd.R], ["Agreement", bd.A]].map(([k, v]) => (
          <div className="fra-item" key={k}>
            <div className="label"><span>{k}</span><b>{(v ?? 0).toFixed(2)}</b></div>
            <span className="meter-track"><span className="meter-fill" style={{ display: "block", width: `${(v ?? 0) * 100}%` }} /></span>
          </div>
        ))}
      </div>
      {bd.F != null && (
        <div style={{ marginTop: 16 }}>
          <DecayChart F={bd.F} R={bd.R} A={bd.A} halfLife={hl} weights={W} thresh={thresh} />
        </div>
      )}
      <div className="xs faint" style={{ marginTop: 6 }}>
        C = {W.F}·F + {W.R}·R + {W.A}·A · computed from the data, never by the model
      </div>
    </div>
  );
}

function RiskBox({ card }) {
  const r = card.risk_hint;
  const disputed = r?.note?.match(/\$([\d,]+) disputed/);
  const valid = until(card.expires_at);
  const validText = card.status === "debating" || !card.expires_at ? "—" : valid || "Expired · re-verify";
  return (
    <div className="box">
      <span className="label">Cost of being wrong</span>
      <div className="big-num" style={{ marginTop: 6 }}>{money(r?.exposure)}</div>
      <div className="xs faint">expected revenue × (1 − confidence)</div>
      <dl className="kv" style={{ marginTop: 16 }}>
        <dt>Expected revenue</dt><dd>{money(r?.value_at_stake)}</dd>
        <dt>Win probability</dt><dd>{pct(r?.win_probability)}</dd>
        {disputed && (<><dt>Disputed amount</dt><dd>${disputed[1]}</dd></>)}
        <dt>Valid for</dt><dd style={{ color: validText.startsWith("Expired") ? "var(--critical-text)" : undefined }}>{validText}</dd>
        <dt>Severity</dt><dd><Severity level={card.severity} /></dd>
      </dl>
    </div>
  );
}

function WhySection({ card }) {
  if (!card.counterfactuals?.length) return null;
  const staleWinner = card.debates?.[0]?.verdict?.winner;
  return (
    <div className="dv-section">
      <span className="label">Why this answer</span>
      {card.counterfactuals.map((c, i) => (
        <div className="why" key={i}>
          <div className="why-title">
            {c.field === "record" ? (staleWinner === "A" ? "Why the record still holds" : "Why re-verify first")
              : c.rejected_value ? `Why not ${c.rejected_value}?` : `Why ${FIELD[c.field] || c.field} is unresolved`}
          </div>
          <p>{c.why_it_lost}</p>
          {c.losing_argument && (
            <details className="small faint" style={{ marginTop: 6 }}>
              <summary style={{ cursor: "pointer" }}>Losing argument</summary>
              <p className="small" style={{ margin: "6px 0 0" }}>{c.losing_argument}</p>
            </details>
          )}
        </div>
      ))}
    </div>
  );
}

function Summary({ card, config }) {
  return (
    <>
      <div className="dv-section">
        <span className="label">Resolution</span>
        <Resolution card={card} />
      </div>
      <div className="dv-section cols">
        <ConfidenceBox card={card} config={config} />
        <RiskBox card={card} />
      </div>
      <WhySection card={card} />
    </>
  );
}

/* ================================================================== debate */
function Claims({ arg, evidence, hl, setHl }) {
  if (!arg) return <p className="small faint">No argument - no debate ran for this fact.</p>;
  return (
    <>
      <ul className="claims">
        {arg.claims.map((c, i) => (
          <li key={i}>
            {c.text}
            <span className="eids">
              {c.evidence_ids.map((id) => (
                <span key={id} title={evidence[id]?.summary}><EvidenceId id={id} hl={hl} onHover={setHl} /></span>
              ))}
            </span>
          </li>
        ))}
      </ul>
      {arg.weaknesses_of_other_side?.length > 0 && (
        <div className="rebuttal">{arg.weaknesses_of_other_side.map((w, i) => <div key={i}>{w}</div>)}</div>
      )}
    </>
  );
}

function DebateBlock({ d, card, config, evidence }) {
  const [hl, setHl] = useState(null);
  const v = d.verdict;
  const stale = d.reason === "stale";
  const title = (s) => (stale ? (s.value === "holds" ? "Record still holds" : "Re-verify first") : s.value);
  const rules = d.provider === "rules";
  const cons = d.consistency;
  return (
    <div className="debate-block">
      <div className="row" style={{ marginBottom: 8 }}>
        <span className="strong">{stale ? "Stale record review" : FIELD[d.field] || d.field}</span>
        {!stale && <span className="badge">{card.discrepancies?.find((x) => x.field === d.field)?.label || "Conflict"}</span>}
      </div>
      <div className="debate-meta">
        {d.cache_hit ? <span><ShieldCheck size={13} /> Reused cached debate · 0 calls</span>
          : rules ? <span><TriangleAlert size={13} /> No debate · rule-based answer</span>
          : <span>{d.llm_calls} LLM calls</span>}
        {!d.cache_hit && d.duration_ms > 0 && <span><Clock size={13} /> {duration(d.duration_ms)}</span>}
        <span className="mono">{d.provider}/{d.model}</span>
      </div>
      {!rules && (
        <div className="debate">
          {[["A", "Proponent", d.side_a, d.proponent], ["B", "Challenger", d.side_b, d.challenger]].map(([k, role, side, arg]) => (
            <div key={k} className={`side ${v.winner === k ? "win" : ""}`}>
              <div className="side-head">
                <span className="label">{role}</span>
                {side.sources?.length > 0 && <span className="xs faint">{side.sources.map((s) => SOURCE[s]).join(" + ")}</span>}
                <span className="grow" />
                {v.winner === k && <span className="status" style={{ fontSize: 12 }}><CircleCheck size={13} color="var(--good)" />Won</span>}
              </div>
              <div className="side-claim">{title(side)}</div>
              <Claims arg={arg} evidence={evidence} hl={hl} setHl={setHl} />
            </div>
          ))}
        </div>
      )}
      <div className="verdict">
        <div className="verdict-head">
          <span className="label">Judge</span>
          <span className="verdict-title">
            {v.winner === "neither" ? "No clear winner" : `Ruled for ${title(v.winner === "A" ? d.side_a : d.side_b)}`}
          </span>
          {v.needs_human_review && <span className="status"><TriangleAlert size={13} color="var(--critical)" />Flagged for review</span>}
        </div>
        <p>{v.reasoning}</p>
        <div className="row wrap" style={{ gap: 4, marginTop: 10 }}>
          <span className="xs faint" style={{ marginRight: 4 }}>Relied on</span>
          {v.evidence_ids.map((id) => <span key={id} title={evidence[id]?.summary}><EvidenceId id={id} hl={hl} onHover={setHl} /></span>)}
        </div>
        {v.residual_uncertainty && <p className="small faint" style={{ marginTop: 10 }}>Residual uncertainty: {v.residual_uncertainty}</p>}
        <div className="checks">
          {!d.fallback_used && (
            <div className="check"><CircleCheck size={14} color="var(--good)" />
              <span>All {v.evidence_ids.length} cited evidence IDs exist in the evidence packet.</span></div>
          )}
          {cons ? (
            <div className="check">
              {cons.agreed ? <CircleCheck size={14} color="var(--good)" /> : <Split size={14} color="var(--critical)" />}
              <span>Position-swap check: {cons.agreed ? "the judge reached the same verdict with the sides swapped." : cons.note}</span>
            </div>
          ) : !rules && !stale && !d.cache_hit && (
            <div className="check"><span style={{ width: 14 }} /><span className="faint">Position-swap check runs above {money(config?.consistency_check_min_stake, { compact: true })} expected revenue.</span></div>
          )}
          {d.fallback_used && !rules && (
            <div className="check"><TriangleAlert size={14} color="var(--critical)" /><span>Judge output failed validation; a rule-based verdict was used.</span></div>
          )}
          {d.errors?.filter((e) => !e.includes("position bias")).map((e, i) => (
            <div className="check" key={i}><X size={14} color="var(--critical)" /><span className="mono xs">{e}</span></div>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ================================================================== evidence / history */
function EvidenceTab({ card }) {
  const [only, setOnly] = useState("all");
  const rows = card.evidence.filter((e) => only === "all" || e.cited);
  return (
    <div className="dv-section">
      <div className="row" style={{ marginBottom: 12 }}>
        <span className="label grow">{card.evidence.length} items · {card.evidence.filter((e) => e.cited).length} cited by the judge</span>
        <Segmented label="Evidence filter" value={only} onChange={setOnly}
          options={[{ value: "all", label: "All" }, { value: "cited", label: "Cited" }]} />
      </div>
      <div className="box" style={{ padding: 0 }}>
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>ID</th><th>Kind</th><th>System</th><th>Detail</th><th /></tr></thead>
            <tbody>
              {rows.map((e) => (
                <tr key={e.id}>
                  <td><span className="eid">{e.id}</span></td>
                  <td className="small muted">{e.kind}</td>
                  <td className="small">{SOURCE[e.source] || e.source}</td>
                  <td className="small muted">{e.summary.replace(/^(CRM|FIN|PIPE|FINANCE|PIPELINE)\s/, "")}</td>
                  <td>{e.cited && <span className="status" style={{ fontSize: 12 }}><Check size={13} color="var(--good)" />Cited</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function HistoryTab({ card }) {
  const [audit, setAudit] = useState(null);
  useEffect(() => {
    api.deal(card.deal_id).then((d) => setAudit(d.audit.filter((a) => card.fields.includes(a.field) || a.field === "record").slice(0, 12))).catch(() => setAudit([]));
  }, [card.deal_id, card.id]);
  const items = [
    { at: card.created_at, title: `Detected by ${card.origin}`, detail: card.query },
    card.resolved_at && card.path !== "direct" && { at: card.resolved_at, title: card.path === "provisional" ? "Provisional answer ready" : "Verdict ready",
      detail: `decided in ${duration(card.time_to_decision_ms)}` },
    ...(card.approvals || []).map((a) => ({ at: a.at, title: `${a.action === "approve" ? "Approved" : "Rejected"} by ${a.actor}`,
      detail: [a.note && `“${a.note}”`, a.effect].filter(Boolean).join(" · ") })),
  ].filter(Boolean);
  return (
    <>
      <div className="dv-section">
        <span className="label">Decision</span>
        <ul className="timeline">
          {items.map((it, i) => (
            <li key={i}>
              <span className="tl-icon"><Check size={10} /></span>
              <div className="row"><span className="tl-title grow">{it.title}</span><span className="tl-time">{ago(it.at)}</span></div>
              {it.detail && <div className="tl-detail">{it.detail}</div>}
            </li>
          ))}
        </ul>
      </div>
      <div className="dv-section">
        <span className="label">Source changes for these fields</span>
        {audit == null ? <div className="small faint">Loading…</div> : (
          <ul className="timeline">
            {audit.map((a) => (
              <li key={a.id}>
                <span className="tl-icon" style={{ fontSize: 8, fontWeight: 700 }}>{SOURCE[a.source]?.[0]}</span>
                <div className="row"><span className="tl-title grow">{SOURCE[a.source]} · {FIELD[a.field] || a.field}</span><span className="tl-time">{ago(a.changed_at)}</span></div>
                <div className="tl-detail">
                  {a.old_value ?? "—"} → {a.new_value} · {a.changed_by} <span className="faint">({a.reason})</span> <span className="eid" style={{ marginLeft: 4 }}>{a.evidence_id}</span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}

/* ================================================================== action bar */
function Stepper({ card, highStakes }) {
  const order = ["arguing", "judging", ...(highStakes && card.reason === "conflict" ? ["verifying"] : [])];
  const label = { arguing: "Proponent & challenger", judging: "Judge", verifying: "Swap check" };
  const cur = order.indexOf(card.progress?.stage ?? "arguing");
  return (
    <div className="stepper" aria-live="polite">
      {order.map((s, i) => (
        <React.Fragment key={s}>
          {i > 0 && <span className="step-line" />}
          <span className={`step ${i < cur ? "done" : i === cur ? "now" : ""}`}>
            {i < cur ? <Check size={13} /> : i === cur ? <LoaderCircle size={13} className="spin" /> : <span className="dot" style={{ background: "var(--line-2)" }} />}
            {label[s]}
          </span>
        </React.Fragment>
      ))}
      {card.progress?.total > 1 && <span className="xs faint">· fact {card.progress.index + 1} of {card.progress.total}</span>}
    </div>
  );
}

function ActionBar({ card, config, onDecided }) {
  const { actor, run } = useArbiter();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [who, setWho] = useState(false);
  const pending = useRef(null);
  const whoRef = useRef(null);
  useEffect(() => setNote(""), [card.id]);

  const decide = async (action, name = actor) => {
    if (!name) { pending.current = action; setWho(true); return; }
    setBusy(true);
    const r = await run(() => api.approve(card.id, { action, actor: name, note }), {
      success: (c) => ({ title: `${card.deal_id} ${action === "approve" ? "approved" : "rejected"}`, description: c.status_note }),
      error: "Could not record the decision",
    });
    setBusy(false);
    if (r) onDecided?.(r);
  };

  useEffect(() => {
    const onKey = (e) => {
      if (!APPROVABLE.has(card.status) || e.metaKey || e.ctrlKey || e.altKey) return;
      if (["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName)) return;
      if (e.key === "a") { e.preventDefault(); decide("approve"); }
      if (e.key === "r") { e.preventDefault(); decide("reject"); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  let content;
  if (card.status === "debating") {
    content = <Stepper card={card} highStakes={(card.risk_hint?.value_at_stake || 0) >= (config?.consistency_check_min_stake ?? 1e12)} />;
  } else if (APPROVABLE.has(card.status)) {
    content = (
      <>
        <button ref={whoRef} className="who" onClick={() => setWho(true)} title="Change reviewer">
          <span className="avatar" style={{ width: 20, height: 20, fontSize: 10 }}>{initials(actor)}</span>
          {actor ? `as ${actor}` : "Set reviewer"}
        </button>
        <input className="input grow" placeholder="Add a note (optional)" value={note} onChange={(e) => setNote(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) decide("approve"); }} aria-label="Decision note" />
        <span className="grow" />
        <button className="btn danger" disabled={busy} onClick={() => decide("reject")}>Reject <Kbd>R</Kbd></button>
        <button className="btn primary" disabled={busy} onClick={() => decide("approve")}><Check size={14} /> Approve <Kbd>A</Kbd></button>
        <IdentityPopover open={who} onClose={() => { setWho(false); pending.current = null; }} anchorRef={whoRef} align="left"
          onSaved={(name) => { const a = pending.current; pending.current = null; if (a) decide(a, name); }} />
      </>
    );
  } else if (card.path === "direct") {
    content = <span className="small muted row"><CircleCheck size={14} color="var(--s-direct)" />Answered directly - all systems agree and the data is fresh. Nothing to approve.</span>;
  } else {
    const a = card.approvals?.[card.approvals.length - 1];
    content = (
      <span className="row small" style={{ gap: 10 }}>
        <StatusBadge status={card.status} />
        {a && <span className="muted truncate">by {a.actor} · {ago(a.at)} · {a.effect?.replace("Action taken: ", "")}</span>}
        {!a && <span className="muted truncate">{card.status_note}</span>}
      </span>
    );
  }
  return <div className="actionbar">{content}</div>;
}

/* ================================================================== main */
export default function DecisionView({ id, summaryKey, onPrev, onNext, hasPrev, hasNext, onDecided, onBack }) {
  const { config } = useArbiter();
  const [card, setCard] = useState(null);
  const [tab, setTab] = useState("summary");
  const [err, setErr] = useState(null);

  useEffect(() => {
    let alive = true;
    api.decision(id).then((c) => { if (alive) { setCard(c); setErr(null); } }).catch((e) => alive && setErr(e.message));
    return () => { alive = false; };
  }, [id, summaryKey]);
  useEffect(() => {
    if (card?.status !== "debating") return;
    const t = setInterval(() => api.decision(card.id).then(setCard).catch(() => {}), 800);
    return () => clearInterval(t);
  }, [card?.id, card?.status]);
  useEffect(() => setTab("summary"), [id]);

  const evidence = useMemo(() => Object.fromEntries((card?.evidence || []).map((e) => [e.id, e])), [card]);

  if (err) return <div className="dv"><div className="placeholder">Could not load this decision. {err}</div></div>;
  if (!card || String(card.id) !== String(id)) return <div className="dv"><div className="placeholder"><LoaderCircle className="spin" size={18} /></div></div>;

  const exportJson = () => {
    const blob = new Blob([JSON.stringify(card, null, 2)], { type: "application/json" });
    const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: `arbiter-decision-${card.id}.json` });
    a.click();
    URL.revokeObjectURL(a.href);
  };
  const tabs = [
    { value: "summary", label: "Summary" },
    { value: "debate", label: "Debate", count: card.debates?.length || undefined },
    { value: "evidence", label: "Evidence", count: card.evidence.length },
    { value: "history", label: "History" },
  ];

  return (
    <div className="dv">
      <div className="dv-head">
        <div className="dv-title">
          {onBack && <button className="icon-btn" onClick={onBack} aria-label="Back to queue"><ArrowLeft size={16} /></button>}
          <h2 className="mono">{card.deal_id}</h2>
          <span className="co truncate">{card.company}</span>
          <span className="grow" />
          <button className="icon-btn" onClick={onPrev} disabled={!hasPrev} aria-label="Previous decision" title="Previous (K)"><ChevronUp size={16} /></button>
          <button className="icon-btn" onClick={onNext} disabled={!hasNext} aria-label="Next decision" title="Next (J)"><ChevronDown size={16} /></button>
          <button className="icon-btn" onClick={() => navigate("records", card.deal_id)} aria-label="Open record" title="Open record"><Database size={15} /></button>
          <button className="icon-btn" onClick={exportJson} aria-label="Export decision" title="Export decision (JSON)"><Download size={15} /></button>
        </div>
        <div className="dv-meta">
          <StatusBadge status={card.status} progress={card.progress} />
          <ReasonBadge reason={card.reason} path={card.path} />
          {[...new Map((card.discrepancies || []).filter((d) => d.type !== "stale_record").map((d) => [d.type, d])).values()]
            .map((d) => <Discrepancy key={d.type} d={d} />)}
          <Severity level={card.severity} />
          <span className="xs faint">#{card.id} · {ago(card.created_at)}</span>
        </div>
      </div>
      <Tabs value={tab} onChange={setTab} tabs={tabs} />
      <div className="dv-body">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div key={`${card.id}-${tab}`} className="dv-inner" {...fade}>
            {tab === "summary" && <Summary card={card} config={config} />}
            {tab === "debate" && (card.debates?.length
              ? card.debates.map((d, i) => <DebateBlock key={i} d={d} card={card} config={config} evidence={evidence} />)
              : <div className="placeholder" style={{ height: 240 }}>{card.status === "debating" ? "The debate is running…" : "No debate - this answer came straight from agreeing, fresh data."}</div>)}
            {tab === "evidence" && <EvidenceTab card={card} />}
            {tab === "history" && <HistoryTab card={card} />}
          </motion.div>
        </AnimatePresence>
      </div>
      <ActionBar card={card} config={config} onDecided={(c) => { setCard(c); onDecided?.(c); }} />
    </div>
  );
}
