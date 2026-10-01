import React, { useMemo } from "react";
import {
  ArrowRight, CircleCheck, CircleX, FastForward, Gavel, Pencil, Radio, RotateCcw, TriangleAlert, Zap,
} from "lucide-react";
import { BarList, GateBar, Sparkline } from "../components/charts.jsx";
import { AnimatedNumber, Card, Meter, Page, Severity } from "../components/ui.jsx";
import { OPEN, SOURCE, ago, money, pct } from "../lib/format.js";
import { navigate } from "../lib/router.js";
import { useArbiter } from "../lib/store.jsx";

const EVENT = {
  detected: { Icon: TriangleAlert, color: "var(--s-conflict)" },
  resolved: { Icon: Gavel, color: "var(--text-2)" },
  approved: { Icon: CircleCheck, color: "var(--good)" },
  rejected: { Icon: CircleX, color: "var(--text-3)" },
  drift: { Icon: Zap, color: "var(--brand)" },
  edit: { Icon: Pencil, color: "var(--text-2)" },
  reset: { Icon: RotateCcw, color: "var(--text-2)" },
  clock: { Icon: FastForward, color: "var(--text-2)" },
  alert: { Icon: Radio, color: "var(--critical)" },
};

function Stat({ label, children, note, foot }) {
  return (
    <section className="card stat span-3">
      <span className="label">{label}</span>
      <div className="stat-value">{children}</div>
      {note && <div className="stat-note">{note}</div>}
      {foot && <div className="stat-foot">{foot}</div>}
    </section>
  );
}

export function ActivityList({ events, limit = 10, onOpen }) {
  if (!events.length) return <div className="small faint" style={{ padding: "8px 16px" }}>No activity yet.</div>;
  return (
    <ul className="list">
      {events.slice(0, limit).map((e) => {
        const k = EVENT[e.kind] || EVENT.resolved;
        const Row = e.decision_id && onOpen ? "button" : "div";
        return (
          <li key={e.id}>
            <Row className="list-row" onClick={Row === "button" ? () => onOpen(e) : undefined} style={{ alignItems: "flex-start" }}>
              <span className="ev-icon" style={{ color: k.color }}><k.Icon size={13} /></span>
              <span className="col grow">
                <span className="truncate" style={{ fontWeight: 500 }}>{e.title}</span>
                {e.detail && <span className="xs faint truncate">{e.detail}</span>}
              </span>
              <span className="xs faint" style={{ whiteSpace: "nowrap" }}>{ago(e.at, { short: true })}</span>
            </Row>
          </li>
        );
      })}
    </ul>
  );
}

export default function Overview() {
  const { stats, decisions, activity, health, openCount } = useArbiter();
  const scan = stats?.last_scan;
  const budget = stats?.budget;
  const review = stats?.review;

  const attention = useMemo(
    () => decisions.filter((d) => OPEN.has(d.status))
      .sort((a, b) => (b.risk_hint?.exposure || 0) - (a.risk_hint?.exposure || 0)).slice(0, 6),
    [decisions]
  );
  const trend = (stats?.history || []).slice(-40).map((p) => ({ value: p.conflicts + p.stale, at: p.at }));
  const types = Object.entries(review?.by_type || {}).sort((a, b) => b[1] - a[1]).map(([label, value]) => ({ label, value, color: label === "Stale record" ? "var(--s-stale)" : undefined }));
  const high = review?.by_severity?.high || 0;

  return (
    <Page>
      <div className="page-head">
        <div>
          <h1 className="page-title">Overview</h1>
          <div className="page-sub">
            {scan ? `${scan.deals} deals across CRM, Finance and Pipeline · scanned ${ago(scan.at)}` : "Waiting for the first scan…"}
          </div>
        </div>
        <div className="page-actions">
          <button className="btn primary" onClick={() => navigate("review")} disabled={!openCount}>
            Review {openCount} open <ArrowRight size={14} />
          </button>
        </div>
      </div>

      <div className="grid">
        <Stat label="Facts monitored" note={scan ? `${scan.deals} deals · 3 systems` : "—"}
          foot={<span className="xs faint">Last scan took {scan?.scan_ms ?? "—"} ms</span>}>
          <AnimatedNumber value={scan?.facts_scanned} />
        </Stat>
        <Stat label="Answered directly" note={scan ? `${scan.direct} facts agreed and were fresh` : "—"}
          foot={<span className="xs faint">No LLM involved</span>}>
          <AnimatedNumber value={scan ? (scan.direct / scan.facts_scanned) * 100 : null} format={(v) => `${v.toFixed(1)}%`} />
        </Stat>
        <Stat label="Open decisions" note={high ? `${high} high severity` : "Nothing high severity"}
          foot={<div className="grow"><Sparkline points={trend} format={(p) => <><b>{p.value}</b><span className="k">open · {ago(p.at, { short: true })}</span></>} /></div>}>
          <AnimatedNumber value={openCount} />
        </Stat>
        <Stat label="LLM usage" note={budget ? `${budget.debates_run} of ${budget.debates_cap} debates · ${budget.cache_hits} cache hits` : "—"}
          foot={<div className="grow"><Meter value={budget ? budget.debates_run / budget.debates_cap : 0} width="100%"
            color={budget && budget.debates_run >= budget.debates_cap ? "var(--critical)" : "var(--text-2)"} hideValue /></div>}>
          <AnimatedNumber value={budget?.llm_calls} /><small>calls</small>
        </Stat>

        <Card className="span-8" title="How every fact was routed" meta="Only conflicting or stale facts reach the debate">
          {scan && (
            <GateBar segments={[
              { key: "direct", label: "Answered directly", value: scan.direct, color: "var(--s-direct)" },
              { key: "conflict", label: "Conflict", value: scan.conflicts, color: "var(--s-conflict)" },
              { key: "stale", label: "Stale", value: scan.stale, color: "var(--s-stale)" },
            ]} />
          )}
          {types.length > 0 && (
            <div style={{ marginTop: 22 }}>
              <div className="label" style={{ marginBottom: 10 }}>Discrepancy types this session</div>
              <BarList items={types} color="var(--s-conflict)" />
            </div>
          )}
        </Card>

        <Card className="span-4" title="Needs attention" meta="by exposure" bodyClass="card-body flush"
          foot={<button className="btn ghost sm" onClick={() => navigate("review")}>Open review queue <ArrowRight size={13} /></button>}>
          {attention.length === 0 ? (
            <div className="small faint" style={{ padding: "8px 16px 12px" }}>All clear - every system agrees.</div>
          ) : (
            <ul className="list">
              {attention.map((d) => (
                <li key={d.id}>
                  <button className="list-row" onClick={() => navigate("review", d.id)}>
                    <Severity level={d.severity} />
                    <span className="col grow">
                      <span className="row" style={{ gap: 6 }}><span className="mono strong">{d.deal_id}</span><span className="truncate muted">{d.company}</span></span>
                      <span className="xs faint truncate">{d.discrepancies?.map((x) => x.label).join(", ") || (d.status === "debating" ? "Debating…" : d.reason)}</span>
                    </span>
                    <span className="small num" style={{ whiteSpace: "nowrap" }}>{money(d.risk_hint?.exposure, { compact: true })}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card className="span-8" title="Source health" meta="Trust is earned from agreement and correction history" bodyClass="card-body flush">
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>System</th><th>Agreement</th><th>Reliability</th><th className="num">Median age</th>
                  <th className="num">Outlier facts</th><th className="num">Debates lost</th><th className="num">Corrections 90d</th>
                </tr>
              </thead>
              <tbody>
                {health.map((h) => (
                  <tr key={h.source}>
                    <td className="strong">{SOURCE[h.source]}</td>
                    <td><Meter value={h.agreement_rate} /></td>
                    <td><Meter value={h.reliability} /></td>
                    <td className="num">{h.median_age_days}d</td>
                    <td className="num">{h.open_outliers}</td>
                    <td className="num">{h.debates_lost}</td>
                    <td className="num">{h.corrections_90d}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card className="span-4" title="Activity" bodyClass="card-body flush">
          <ActivityList events={activity} limit={8} onOpen={(e) => navigate("review", e.decision_id)} />
        </Card>

        {review && review.decided > 0 && (
          <Card className="span-12" title="Review analytics">
            <div className="row wrap" style={{ gap: 40 }}>
              <div className="col"><span className="label">Decided</span><span className="legend-val">{review.decided}</span></div>
              <div className="col"><span className="label">Approval rate</span><span className="legend-val">{pct(review.approval_rate)}</span></div>
              <div className="col"><span className="label">Flagged for close review</span><span className="legend-val">{pct(review.flagged_rate)}</span></div>
              <div className="col"><span className="label">Median time to human decision</span>
                <span className="legend-val">{review.median_review_s != null ? `${Math.round(review.median_review_s)} s` : "—"}</span></div>
            </div>
          </Card>
        )}
      </div>
    </Page>
  );
}
