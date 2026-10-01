import React, { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { CircleCheck, Search } from "lucide-react";
import { Discrepancy, EASE, ReasonBadge, Segmented, Severity, StatusBadge } from "../components/ui.jsx";
import { OPEN, ago, fieldList, money } from "../lib/format.js";
import { navigate } from "../lib/router.js";
import { useArbiter } from "../lib/store.jsx";
import DecisionView from "./DecisionView.jsx";

const isMobile = () => window.matchMedia("(max-width: 860px)").matches;

function QueueItem({ d, on, fresh }) {
  return (
    <motion.button layout="position" className={`q-item ${on ? "on" : ""} ${fresh ? "fresh" : ""}`} onClick={() => navigate("review", d.id)}
      initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.98 }} transition={{ duration: 0.22, ease: EASE }} aria-current={on ? "true" : undefined}>
      <div className="q-l1">
        <span className="q-deal">{d.deal_id}</span>
        <span className="q-co truncate">{d.company}</span>
        <span className="q-time">{ago(d.created_at, { short: true })}</span>
      </div>
      <div className="q-l2">
        {d.discrepancies?.length ? <Discrepancy d={d.discrepancies[0]} /> : <ReasonBadge reason={d.reason} path={d.path} />}
        {d.discrepancies?.length > 1 && <span className="xs faint">+{d.discrepancies.length - 1}</span>}
        <StatusBadge status={d.status} progress={d.progress} size={13} />
      </div>
      <div className="q-l2" style={{ marginTop: 6 }}>
        <span className="xs faint truncate grow">{fieldList(d.fields)}</span>
        <Severity level={d.severity} />
        {d.risk_hint && <span className="xs faint num">{money(d.risk_hint.exposure, { compact: true })}</span>}
      </div>
    </motion.button>
  );
}

export default function Review({ id }) {
  const { decisions, fresh } = useArbiter();
  const [view, setView] = useState("open");
  const [sort, setSort] = useState("exposure");
  const [q, setQ] = useState("");

  const counts = useMemo(() => ({
    open: decisions.filter((d) => OPEN.has(d.status)).length,
    done: decisions.filter((d) => !OPEN.has(d.status) && d.path !== "direct").length,
    all: decisions.length,
  }), [decisions]);

  const list = useMemo(() => {
    const term = q.trim().toLowerCase();
    let items = decisions.filter((d) =>
      view === "open" ? OPEN.has(d.status) : view === "done" ? !OPEN.has(d.status) && d.path !== "direct" : true);
    if (term) items = items.filter((d) => `${d.deal_id} ${d.company} ${d.fields.join(" ")}`.toLowerCase().includes(term));
    return [...items].sort((a, b) =>
      sort === "exposure" ? (b.risk_hint?.exposure || 0) - (a.risk_hint?.exposure || 0) || b.id - a.id : b.id - a.id);
  }, [decisions, view, sort, q]);

  const selected = id != null ? Number(id) : null;
  const idx = list.findIndex((d) => d.id === selected);

  // Desktop: always have something open. Mobile: the list is the landing view.
  useEffect(() => {
    if (selected == null && list.length && !isMobile()) navigate("review", list[0].id);
  }, [selected, list]);

  const go = (delta) => {
    const next = list[idx + delta];
    if (next) navigate("review", next.id);
  };
  useEffect(() => {
    const onKey = (e) => {
      if (e.metaKey || e.ctrlKey || e.altKey || ["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName)) return;
      if (e.key === "j" || e.key === "ArrowDown") { e.preventDefault(); go(1); }
      if (e.key === "k" || e.key === "ArrowUp") { e.preventDefault(); go(-1); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // After a decision, move straight on to the next open item (inbox-zero flow).
  const onDecided = (card) => {
    if (view !== "open") return;
    const rest = list.filter((d) => d.id !== card.id);
    const next = rest[Math.min(Math.max(idx, 0), rest.length - 1)];
    setTimeout(() => (next ? navigate("review", next.id) : navigate("review")), 350);
  };

  const sel = decisions.find((d) => d.id === selected);
  return (
    <div className={`review ${selected != null ? "has-sel" : ""}`}>
      <section className="queue" aria-label="Review queue">
        <div className="queue-head">
          <div className="row">
            <Segmented label="Queue" value={view} onChange={setView} options={[
              { value: "open", label: "Open", count: counts.open },
              { value: "done", label: "Resolved", count: counts.done },
              { value: "all", label: "All", count: counts.all },
            ]} />
            <span className="grow" />
            <select className="input select" style={{ width: "auto", height: 30 }} value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort">
              <option value="exposure">Exposure</option>
              <option value="new">Newest</option>
            </select>
          </div>
          <div className="search">
            <Search size={14} />
            <input className="input" placeholder="Filter by deal, company or field" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
        </div>
        <div className="queue-list">
          {list.length === 0 && (
            <div className="q-empty">
              <CircleCheck size={22} />
              <div className="strong" style={{ color: "var(--text)" }}>{view === "open" ? "Inbox zero" : "Nothing here"}</div>
              <div className="small">{view === "open" ? "Every system agrees. New conflicts appear here automatically." : "No decisions match this view."}</div>
            </div>
          )}
          <AnimatePresence mode="popLayout" initial={false}>
            {list.map((d) => <QueueItem key={d.id} d={d} on={d.id === selected} fresh={fresh.has(d.id)} />)}
          </AnimatePresence>
        </div>
      </section>
      {selected != null ? (
        <DecisionView id={selected}
          summaryKey={sel ? `${sel.status}-${sel.resolved_at}-${sel.decided_at}-${sel.progress?.stage}` : "x"}
          hasPrev={idx > 0} hasNext={idx >= 0 && idx < list.length - 1} onPrev={() => go(-1)} onNext={() => go(1)}
          onDecided={onDecided} onBack={isMobile() ? () => navigate("review") : undefined} />
      ) : (
        <div className="dv"><div className="placeholder"><div><div className="ph-title">Nothing selected</div>Pick a decision from the queue.</div></div></div>
      )}
    </div>
  );
}
