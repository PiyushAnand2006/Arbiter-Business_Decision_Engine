import React from "react";
import {
  Database, GitCompareArrows, Gauge, ShieldCheck, Swords, UserCheck, Wand2,
} from "lucide-react";
import { Card, Page } from "../components/ui.jsx";
import { money } from "../lib/format.js";
import { useArbiter } from "../lib/store.jsx";

const STEPS = [
  { Icon: Database, t: "Ingest", d: "CRM, Finance and Pipeline records, plus their audit logs." },
  { Icon: Wand2, t: "Normalize", d: "Dates, currency, stage names and casing, so formatting never looks like a conflict." },
  { Icon: GitCompareArrows, t: "Compare", d: "Group equal values across systems and find the largest agreeing group." },
  { Icon: Gauge, t: "Score", d: "Freshness, reliability and agreement give every fact a confidence score." },
  { Icon: ShieldCheck, t: "Gate", d: "Agreeing, fresh facts are answered directly. Conflicts and stale facts go on." },
  { Icon: Swords, t: "Debate", d: "A proponent and challenger argue from cited evidence, and a judge rules.", k: "llm" },
  { Icon: UserCheck, t: "Approve", d: "A person approves or rejects. Only then are systems synced.", k: "human" },
];

export default function Engine() {
  const { config: c } = useArbiter();
  return (
    <Page>
      <div className="page-head">
        <div>
          <h1 className="page-title">Engine</h1>
          <div className="page-sub">Everything before the debate is deterministic, so clean data never reaches the model.</div>
        </div>
      </div>
      <div className="grid">
        <Card className="span-12" title="Pipeline">
          <div className="flow">
            {STEPS.map((s, i) => (
              <div key={s.t} className={`flow-step ${s.k || ""}`}>
                {i < STEPS.length - 1 && <span className="flow-line" />}
                <span className="flow-dot"><s.Icon size={14} /></span>
                <h4>{s.t}</h4>
                <p>{s.d}</p>
              </div>
            ))}
          </div>
        </Card>

        <Card className="span-6" title="Confidence">
          <div className="formula">
            F = exp(−ln2 · age / half-life)<br />
            R = 1 − min(0.5, corrections₉₀ / updates₉₀)<br />
            A = largest agreeing group / systems<br />
            <b>C = {c?.weights?.F}·F + {c?.weights?.R}·R + {c?.weights?.A}·A</b>
          </div>
          <dl className="kv" style={{ marginTop: 16 }}>
            <dt>Debate threshold</dt><dd>C &lt; {c?.thresh_low}</dd>
            <dt>Numeric tolerance</dt><dd>±{((c?.numeric_tolerance || 0) * 100).toFixed(1)}%</dd>
            <dt>Reliability window</dt><dd>{c?.reliability_window_days} days</dd>
            {c?.half_life_days && Object.entries(c.half_life_days).filter(([k]) => ["stage", "value", "close_date", "last_contacted"].includes(k))
              .map(([k, v]) => (<React.Fragment key={k}><dt>Half-life · {k.replace("_", " ")}</dt><dd>{v} days</dd></React.Fragment>))}
          </dl>
        </Card>

        <Card className="span-6" title="Cost and guardrails">
          <dl className="kv">
            <dt>Provider</dt><dd className="mono">{c?.llm_provider} / {c?.llm_model}</dd>
            <dt>Calls per conflict</dt><dd>3, plus 1 repair retry at most</dd>
            <dt>Position-swap re-judge</dt><dd>above {money(c?.consistency_check_min_stake, { compact: true })} expected revenue</dd>
            <dt>Session budget</dt><dd>{c?.max_debates_per_session} debates, then provisional</dd>
            <dt>Debate cache</dt><dd>identical conflicts are never re-debated</dd>
            <dt>Citations</dt><dd>must exist in the evidence packet</dd>
            <dt>Invalid output</dt><dd>1 retry, then rule-based fallback</dd>
            <dt>Alerts</dt><dd>{c?.alerts_enabled ? "webhook enabled" : "off (set ALERT_WEBHOOK_URL)"}</dd>
            <dt>Execution</dt><dd>never automatic</dd>
          </dl>
        </Card>
      </div>
    </Page>
  );
}
