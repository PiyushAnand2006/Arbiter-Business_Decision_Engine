import React, { useEffect, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { ChevronRight, Info } from "lucide-react";
import { EASE, Meter, Page, ReasonBadge } from "../components/ui.jsx";
import { api } from "../lib/api.js";
import { money, pct } from "../lib/format.js";
import { navigate } from "../lib/router.js";
import { useArbiter } from "../lib/store.jsx";

export default function Followups() {
  const { tick, decisions } = useArbiter();
  const [data, setData] = useState(null);
  const [showExcluded, setShowExcluded] = useState(true);
  useEffect(() => { api.priorities().then(setData).catch(() => {}); }, [Math.floor(tick / 4)]);
  const max = Math.max(1, ...(data?.ranked || []).map((r) => r.score));
  const openDecision = (dealId) => {
    const d = decisions.find((x) => x.deal_id === dealId && x.path !== "direct");
    navigate(d ? "review" : "records", d ? d.id : dealId);
  };

  return (
    <Page>
      <div className="page-head">
        <div>
          <h1 className="page-title">Follow-ups</h1>
          <div className="page-sub">Open deals ranked by expected revenue and how long since the last contact.</div>
        </div>
        <span className="page-actions xs faint row" title={data?.method}><Info size={13} /> value × win probability × contact urgency</span>
      </div>
      <section className="card" style={{ overflow: "hidden" }}>
        <div className="table-wrap">
          <table className="table hover">
            <thead>
              <tr>
                <th className="num" style={{ width: 40 }}>#</th><th>Deal</th><th>Stage</th><th className="num">Value</th>
                <th className="num">Win prob.</th><th className="num">Last contact</th><th>Confidence</th><th style={{ width: 160 }}>Priority</th>
              </tr>
            </thead>
            <tbody>
              {!data && <tr><td colSpan={8} className="faint">Loading…</td></tr>}
              {data?.ranked.map((r) => (
                <tr key={r.deal_id} onClick={() => navigate("records", r.deal_id)}>
                  <td className="num faint">{r.rank}</td>
                  <td><div className="mono strong">{r.deal_id}</div><div className="cell-sub">{r.company} · {r.owner}</div></td>
                  <td>{r.stage}</td>
                  <td className="num">{money(r.value)}</td>
                  <td className="num">{pct(r.win_probability)}</td>
                  <td className="num">{r.days_since_contact}d ago</td>
                  <td><Meter value={r.confidence} thresh={0.6} /></td>
                  <td>
                    <span className="meter">
                      <span className="meter-track" style={{ width: 110 }}>
                        <span className="meter-fill" style={{ display: "block", width: `${(r.score / max) * 100}%`, background: "var(--text-2)" }} />
                      </span>
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {data?.flagged.length > 0 && (
        <section className="card" style={{ marginTop: 16, overflow: "hidden" }}>
          <button className="card-head" style={{ width: "100%", border: 0, background: "transparent", paddingBottom: 12, textAlign: "left" }}
            onClick={() => setShowExcluded((v) => !v)} aria-expanded={showExcluded}>
            <motion.span animate={{ rotate: showExcluded ? 90 : 0 }} transition={{ duration: 0.2 }} style={{ display: "inline-flex" }}>
              <ChevronRight size={15} />
            </motion.span>
            <h3 className="card-title">Not ranked until the data is fixed</h3>
            <span className="card-meta">{data.flagged.length} deals with conflicting or stale facts</span>
          </button>
          <AnimatePresence initial={false}>
            {showExcluded && (
              <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.25, ease: EASE }} style={{ overflow: "hidden" }}>
                <table className="table hover">
                  <tbody>
                    {data.flagged.map((r) => (
                      <tr key={r.deal_id} onClick={() => openDecision(r.deal_id)}>
                        <td style={{ width: 40 }} />
                        <td><div className="mono strong">{r.deal_id}</div><div className="cell-sub">{r.company}</div></td>
                        <td>{r.stage}</td>
                        <td className="num">{money(r.value)}</td>
                        <td><div className="row wrap" style={{ gap: 6 }}>
                          {r.flags.map((f) => <ReasonBadge key={f} reason={f.includes("stale") ? "stale" : "conflict"} />)}
                          <span className="xs faint">{r.flags.join(", ")}</span>
                        </div></td>
                        <td className="r"><span className="xs faint row" style={{ justifyContent: "flex-end" }}>Resolve <ChevronRight size={13} /></span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </motion.div>
            )}
          </AnimatePresence>
        </section>
      )}
    </Page>
  );
}
