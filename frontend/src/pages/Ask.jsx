import React, { useEffect, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ArrowRight, ArrowUp, CircleCheck, LoaderCircle, Search } from "lucide-react";
import { EASE, Meter, Page, ReasonBadge, StatusBadge } from "../components/ui.jsx";
import { api } from "../lib/api.js";
import { APPROVABLE, FIELD, money, pct } from "../lib/format.js";
import { navigate } from "../lib/router.js";
import { useArbiter } from "../lib/store.jsx";

const SUGGESTIONS = [
  { q: "What is the status and value of deal D1007?", tag: "Systems agree" },
  { q: "What is the status and value of deal D1042?", tag: "Systems disagree" },
  { q: "Is deal D1019 still accurate?", tag: "Stale record" },
  { q: "Which open deals should we follow up on first?", tag: "Ranking" },
];

function DecisionAnswer({ initial, onChanged }) {
  const [card, setCard] = useState(initial);
  useEffect(() => {
    if (card.status !== "debating") return;
    const t = setInterval(() => api.decision(card.id).then((c) => { setCard(c); if (c.status !== "debating") onChanged(); }).catch(() => {}), 700);
    return () => clearInterval(t);
  }, [card.id, card.status]);
  const debating = card.status === "debating";
  const calls = (card.debates || []).reduce((a, d) => a + (d.llm_calls || 0), 0);
  const cached = (card.debates || []).some((d) => d.cache_hit);
  const how = card.path === "direct" ? "Answered directly · no LLM call"
    : debating ? "Systems disagree - debating" : cached ? "Reused an earlier debate · 0 calls" : `Debated · ${calls} LLM calls`;
  return (
    <>
      <div className="row wrap" style={{ gap: 10, marginBottom: 14 }}>
        <span className="mono strong">{card.deal_id}</span>
        <span className="muted">{card.company}</span>
        <span className="grow" />
        <ReasonBadge reason={card.reason} path={card.path} />
        {card.path !== "direct" && <StatusBadge status={card.status} progress={card.progress} />}
      </div>
      <div className="grid" style={{ gap: 12 }}>
        {card.fields.map((f) => (
          <div key={f} className="span-4 box" style={{ padding: "12px 14px" }}>
            <div className="label">{FIELD[f] || f}</div>
            <div className="res-value" style={{ marginTop: 4 }}>
              {debating ? <span className="res-value pending">…</span> : card.answer?.[f] ?? <span className="res-value bad">Unresolved</span>}
            </div>
          </div>
        ))}
      </div>
      <div className="row wrap" style={{ marginTop: 14, gap: 16 }}>
        <span className="row small muted" style={{ gap: 6 }}>
          {debating ? <LoaderCircle size={14} className="spin" /> : <CircleCheck size={14} color={card.path === "direct" ? "var(--s-direct)" : "var(--good)"} />}
          {how}
        </span>
        <span className="row small muted" style={{ gap: 8 }}>Confidence <Meter value={card.confidence} thresh={0.6} /></span>
        <span className="grow" />
        {card.path !== "direct" && !debating && (
          <button className="btn sm" onClick={() => navigate("review", card.id)}>
            {APPROVABLE.has(card.status) ? "Review & approve" : "Open decision"} <ArrowRight size={13} />
          </button>
        )}
      </div>
    </>
  );
}

function PrioritiesAnswer({ data }) {
  return (
    <>
      <div className="row" style={{ marginBottom: 10 }}>
        <span className="strong">Follow up on these first</span>
        <span className="grow" />
        <button className="btn sm ghost" onClick={() => navigate("followups")}>All follow-ups <ArrowRight size={13} /></button>
      </div>
      <table className="table">
        <tbody>
          {data.ranked.slice(0, 5).map((r) => (
            <tr key={r.deal_id}>
              <td className="num faint" style={{ width: 28 }}>{r.rank}</td>
              <td><span className="mono strong">{r.deal_id}</span> <span className="muted">{r.company}</span></td>
              <td className="small muted">{r.stage}</td>
              <td className="num">{money(r.value)}</td>
              <td className="num small muted">{pct(r.win_probability)} · {r.days_since_contact}d since contact</td>
            </tr>
          ))}
        </tbody>
      </table>
      {data.flagged.length > 0 && (
        <div className="small faint" style={{ marginTop: 10 }}>
          {data.flagged.length} open deals are excluded until their conflicting or stale data is resolved.
        </div>
      )}
    </>
  );
}

export default function Ask() {
  const { run, refresh } = useArbiter();
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [answers, setAnswers] = useState([]);

  const ask = async (text) => {
    const question = (text ?? q).trim();
    if (!question) return;
    setBusy(true);
    const r = await run(() => api.query(question), { error: "Could not answer that" });
    setBusy(false);
    if (r) {
      setAnswers((a) => [{ key: Date.now(), question, r }, ...a].slice(0, 4));
      setQ("");
    }
  };

  return (
    <Page className="page narrow">
      <div className="page-head">
        <div>
          <h1 className="page-title">Ask Arbiter</h1>
          <div className="page-sub">Answers come from the data. The model is only consulted when the systems disagree.</div>
        </div>
      </div>
      <form className="ask-box" onSubmit={(e) => { e.preventDefault(); ask(); }}>
        <Search size={17} />
        <input className="ask-input" value={q} onChange={(e) => setQ(e.target.value)} autoFocus
          placeholder="Ask about a deal, e.g. “status and value of D1042”" aria-label="Question" />
        <button className="ask-go" disabled={busy || !q.trim()} aria-label="Ask">
          {busy ? <LoaderCircle size={16} className="spin" /> : <ArrowUp size={16} />}
        </button>
      </form>
      {answers.length === 0 && (
        <div className="suggest">
          {SUGGESTIONS.map((s) => (
            <button key={s.q} onClick={() => ask(s.q)} disabled={busy}>
              <ArrowRight size={14} color="var(--text-3)" />{s.q}<span className="tag">{s.tag}</span>
            </button>
          ))}
        </div>
      )}
      <AnimatePresence initial={false}>
        {answers.map((a) => (
          <motion.section key={a.key} className="card answer-card" layout
            initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
            transition={{ duration: 0.28, ease: EASE }}>
            <div className="card-head"><span className="small muted">“{a.question}”</span></div>
            <div className="card-body">
              {a.r.type === "decision" ? <DecisionAnswer initial={a.r.card} onChanged={() => refresh(true)} /> : <PrioritiesAnswer data={a.r} />}
            </div>
          </motion.section>
        ))}
      </AnimatePresence>
      {answers.length > 0 && (
        <div className="suggest" style={{ marginTop: 16 }}>
          <div className="label" style={{ padding: "0 12px 4px" }}>Try another</div>
          {SUGGESTIONS.filter((s) => !answers.some((a) => a.question === s.q)).map((s) => (
            <button key={s.q} onClick={() => ask(s.q)} disabled={busy}>
              <ArrowRight size={14} color="var(--text-3)" />{s.q}<span className="tag">{s.tag}</span>
            </button>
          ))}
        </div>
      )}
    </Page>
  );
}
