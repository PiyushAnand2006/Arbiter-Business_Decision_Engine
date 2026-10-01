import React, { useEffect, useState } from "react";
import { Check, CircleCheck, CircleX, LoaderCircle, Play, X } from "lucide-react";
import { BarList } from "../components/charts.jsx";
import { Card, Page } from "../components/ui.jsx";
import { api } from "../lib/api.js";
import { ago, pct } from "../lib/format.js";
import { useArbiter } from "../lib/store.jsx";

const TILES = [
  ["conflict_recall", "Conflict detection recall", (v) => pct(v)],
  ["false_conflict_rate", "False-conflict rate", (v) => pct(v, 1)],
  ["reconciliation_accuracy", "Reconciliation accuracy", (v) => pct(v)],
  ["clean_debate_rate", "Debates on clean records", (v) => pct(v)],
  ["citation_validity", "Citation validity", (v) => pct(v)],
  ["max_time_to_decision_s", "Slowest time to decision", (v) => (v == null ? "—" : `${v.toFixed(2)} s`)],
];

export default function Evaluation() {
  const { stats, run } = useArbiter();
  const [rep, setRep] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.latestEval().then((r) => r?.metrics && setRep(r)).catch(() => {}); }, []);

  const go = async (live) => {
    if (live && !window.confirm(`Run with ${stats?.provider} (${stats?.model})? This makes about 60 real LLM calls.`)) return;
    setBusy(true);
    const r = await run(() => api.runEval(live), { success: { title: "Evaluation complete" }, error: "Evaluation failed" });
    setBusy(false);
    if (r) setRep(r);
  };
  const m = rep?.metrics;
  const target = (k) => rep?.targets?.[k];

  return (
    <Page>
      <div className="page-head">
        <div>
          <h1 className="page-title">Evaluation</h1>
          <div className="page-sub">A fresh copy of the dataset is scanned and debated end to end, then scored against the injected ground truth.</div>
        </div>
        <div className="page-actions">
          {stats?.provider && stats.provider !== "mock" && (
            <button className="btn" disabled={busy} onClick={() => go(true)}>Run with {stats.provider}</button>
          )}
          <button className="btn primary" disabled={busy} onClick={() => go(false)}>
            {busy ? <LoaderCircle size={14} className="spin" /> : <Play size={14} />} Run evaluation
          </button>
        </div>
      </div>

      {!rep ? (
        <Card><div className="placeholder" style={{ height: 180 }}>No evaluation yet. Run one to score the engine.</div></Card>
      ) : (
        <div className="grid">
          {TILES.map(([k, label, f]) => {
            const t = target(k);
            return (
              <section key={k} className="card stat span-4" style={{ minHeight: 0 }}>
                <span className="label">{label}</span>
                <div className="stat-value">{f(m[k])}</div>
                {t && (
                  <span className="status" style={{ marginTop: 4 }}>
                    {t.met ? <CircleCheck size={14} color="var(--good)" /> : <CircleX size={14} color="var(--critical)" />}
                    Target {t.op} {k.endsWith("_s") ? `${t.target} s` : pct(t.target)}
                  </span>
                )}
              </section>
            );
          })}

          <Card className="span-7" title="Reconciliation accuracy" meta={`${rep.items.length} injected cases`}>
            <BarList max={1} format={(v) => pct(v)} items={[
              { label: "Arbiter (debate)", value: m.reconciliation_accuracy },
              { label: "Majority + recency rule", value: m.baseline_accuracy, emphasis: false },
            ]} />
            <p className="xs faint" style={{ margin: "14px 0 0" }}>
              Both are scored on identical evidence. {rep.provider === "mock"
                ? "The mock provider is a deterministic reasoner, not a model - run with a live provider for model numbers."
                : `Model: ${rep.model}.`}
            </p>
          </Card>
          <Card className="span-5" title="Cost">
            <dl className="kv">
              <dt>LLM calls, standard conflict</dt><dd>{m.avg_calls_standard ?? "—"}</dd>
              <dt>Position-swap checks</dt><dd>{m.consistency_checks} · {pct(m.consistency_agreement)} consistent</dd>
              <dt>Total LLM calls</dt><dd>{m.llm_calls}</dd>
              <dt>Facts answered without an LLM</dt><dd>{rep.facts_direct} of {rep.facts_scanned}</dd>
              <dt>Engine scan</dt><dd>{m.scan_ms} ms</dd>
            </dl>
          </Card>

          <Card className="span-12" title="Cases" meta={`${rep.provider}/${rep.model} · ${ago(rep.generated_at)}`} bodyClass="card-body flush">
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr><th>Deal</th><th>Fact</th><th>Injected pattern</th><th>Ground truth</th><th>Arbiter</th><th>Baseline</th><th className="num">Calls</th></tr>
                </thead>
                <tbody>
                  {rep.items.map((it) => (
                    <tr key={`${it.deal_id}-${it.field}`}>
                      <td className="mono strong">{it.deal_id}</td>
                      <td className="small">{it.field.replace("_", " ")}</td>
                      <td className="mono xs muted">{it.pattern}</td>
                      <td>{it.truth}</td>
                      <td><span className="status">{it.arbiter_correct ? <Check size={13} color="var(--good)" /> : <X size={13} color="var(--critical)" />}{it.arbiter}</span></td>
                      <td><span className="status">{it.baseline_correct ? <Check size={13} color="var(--good)" /> : <X size={13} color="var(--critical)" />}{it.baseline}</span></td>
                      <td className="num">{it.llm_calls}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </div>
      )}
    </Page>
  );
}
