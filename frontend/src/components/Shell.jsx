import React, { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { Command } from "cmdk";
import {
  Database, Download, FlaskConical, Inbox, LayoutDashboard, ListOrdered, Menu, MessageSquareText, Moon,
  RefreshCw, RotateCcw, Scale, Search, Sun, Workflow, Zap, FastForward, Cpu, ArrowRight,
} from "lucide-react";
import { api } from "../lib/api.js";
import { fieldList, initials, OPEN } from "../lib/format.js";
import { navigate } from "../lib/router.js";
import { useArbiter } from "../lib/store.jsx";
import { EASE, Kbd, Popover, Segmented, Switch } from "./ui.jsx";

export const PAGES = [
  { key: "overview", label: "Overview", Icon: LayoutDashboard },
  { key: "review", label: "Review", Icon: Inbox },
  { key: "ask", label: "Ask", Icon: MessageSquareText },
  { key: "records", label: "Records", Icon: Database },
  { key: "followups", label: "Follow-ups", Icon: ListOrdered },
  { key: "evaluation", label: "Evaluation", Icon: FlaskConical, group: "insights" },
  { key: "engine", label: "Engine", Icon: Workflow, group: "insights" },
];

/* ------------------------------------------------------------------ sidebar */
export function Sidebar({ page, open, onClose }) {
  const { stats, openCount, run, actor, theme, setTheme } = useArbiter();
  const [whoOpen, setWhoOpen] = useState(false);
  const meRef = useRef(null);
  const item = (p) => (
    <button key={p.key} className={`nav-item ${page === p.key ? "on" : ""}`} aria-current={page === p.key ? "page" : undefined}
      onClick={() => { navigate(p.key); onClose(); }}>
      {page === p.key && <motion.span layoutId="nav-pill" className="nav-pill" transition={{ duration: 0.25, ease: EASE }} />}
      <p.Icon size={16} strokeWidth={1.8} />
      {p.label}
      {p.key === "review" && openCount > 0 && <span className="nav-count">{openCount}</span>}
    </button>
  );
  return (
    <aside className={`sidebar ${open ? "" : "closed"}`} aria-label="Navigation">
      <div className="brand">
        <span className="brand-mark"><Scale size={16} strokeWidth={2.2} /></span>
        <div>
          <div className="brand-name">Arbiter</div>
          <div className="brand-ws">Northwind Systems</div>
        </div>
      </div>
      <nav className="nav-group">{PAGES.filter((p) => !p.group).map(item)}</nav>
      <div className="nav-title">Insights</div>
      <nav className="nav-group" style={{ marginTop: 0 }}>{PAGES.filter((p) => p.group).map(item)}</nav>

      <div className="sidebar-foot">
        {stats && (
          <div className="sys-card">
            <div className="sys-row">
              <span className={`pulse ${stats.monitor_enabled ? "live" : ""}`} />
              <span className="grow">{stats.monitor_enabled ? "Monitoring" : "Monitor paused"}</span>
              <Switch on={stats.monitor_enabled} label="Background monitoring"
                onChange={(v) => run(() => api.monitor(v))} />
            </div>
            <div className="sys-row faint">
              <Cpu size={13} />
              <span className="truncate mono">{stats.model}</span>
            </div>
            {stats.clock_offset_days > 0 && (
              <div className="sys-row" style={{ color: "var(--brand)" }}>
                <FastForward size={13} /> Clock +{stats.clock_offset_days} days
              </div>
            )}
          </div>
        )}
        <div className="row" style={{ gap: 4 }}>
          <button ref={meRef} className="me grow" onClick={() => setWhoOpen(true)} title="Reviewer identity">
            <span className="avatar">{initials(actor)}</span>
            <span className="truncate small">{actor || "Set your name"}</span>
          </button>
          <button className="icon-btn" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}>
            {theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
          </button>
        </div>
        <IdentityPopover open={whoOpen} onClose={() => setWhoOpen(false)} anchorRef={meRef} align="left" />
      </div>
    </aside>
  );
}

export function IdentityPopover({ open, onClose, anchorRef, align, onSaved }) {
  const { actor, setActor } = useArbiter();
  const [v, setV] = useState(actor);
  useEffect(() => setV(actor), [actor, open]);
  return (
    <Popover open={open} onClose={onClose} anchorRef={anchorRef} align={align} width={280}>
      <form className="col" style={{ gap: 8, padding: 8 }}
        onSubmit={(e) => { e.preventDefault(); if (v.trim()) { setActor(v.trim()); onClose(); onSaved?.(v.trim()); } }}>
        <span className="strong small">Reviewer name</span>
        <span className="xs faint">Every approval and rejection is logged under this name.</span>
        <input className="input" autoFocus value={v} onChange={(e) => setV(e.target.value)} placeholder="e.g. Priya · RevOps" />
        <button className="btn primary sm" disabled={!v.trim()}>Save</button>
      </form>
    </Popover>
  );
}

/* ------------------------------------------------------------------ topbar */
export function Topbar({ crumbs, onMenu, onCommand }) {
  const [demo, setDemo] = useState(false);
  const demoRef = useRef(null);
  return (
    <header className="topbar">
      <button className="icon-btn menu-btn" onClick={onMenu} aria-label="Open navigation"><Menu size={17} /></button>
      <nav className="crumbs" aria-label="Breadcrumb">
        {crumbs.map((c, i) => (
          <React.Fragment key={i}>
            {i > 0 && <span className="sep">/</span>}
            {c.onClick ? <button className="btn ghost sm" style={{ padding: "0 4px" }} onClick={c.onClick}>{c.label}</button>
              : <span className={i === crumbs.length - 1 ? "here truncate" : "muted"}>{c.label}</span>}
          </React.Fragment>
        ))}
      </nav>
      <span className="grow" />
      <button className="cmd-trigger" onClick={onCommand} aria-label="Search and commands">
        <Search size={14} /><span className="cmd-text">Search or jump to…</span><Kbd>Ctrl K</Kbd>
      </button>
      <button ref={demoRef} className="btn sm" onClick={() => setDemo((v) => !v)} aria-expanded={demo}>
        <FlaskConical size={14} /> Demo
      </button>
      <DemoMenu open={demo} onClose={() => setDemo(false)} anchorRef={demoRef} />
    </header>
  );
}

/* ------------------------------------------------------------------ demo menu */
function DemoMenu({ open, onClose, anchorRef }) {
  const { stats, run } = useArbiter();
  const offset = stats?.clock_offset_days || 0;
  const act = (fn, opts) => { onClose(); run(fn, opts); };
  const Item = ({ Icon, title, sub, onClick, danger }) => (
    <button className="pop-item" onClick={onClick}>
      <span className="pi-icon" style={danger ? { color: "var(--critical-text)" } : undefined}><Icon size={15} /></span>
      <span className="col"><span className="pi-title">{title}</span><span className="pi-sub">{sub}</span></span>
    </button>
  );
  return (
    <Popover open={open} onClose={onClose} anchorRef={anchorRef} width={320}>
      <Item Icon={RefreshCw} title="Scan now" sub="Re-check every fact across all systems"
        onClick={() => act(api.scan, { success: (r) => ({ title: `Scanned ${r.facts_scanned} facts in ${r.scan_ms} ms`,
          description: `${r.direct} direct · ${r.debate} sent to debate` }) })} />
      <Item Icon={Zap} title="Inject drift" sub="Silently corrupt one value in one system"
        onClick={() => act(() => api.inject({}), { success: (r) => ({ title: `Drift injected into ${r.deal_id}`,
          description: `${r.source}.${r.field}: ${r.old} → ${r.new}` }) })} />
      <div className="pop-sep" />
      <div className="pop-row">
        <span className="pi-icon"><FastForward size={15} /></span>
        <span className="col grow"><span className="pi-title">Engine clock</span><span className="pi-sub">Watch confidence decay</span></span>
      </div>
      <div style={{ padding: "0 10px 8px" }}>
        <Segmented label="Clock offset" value={offset} onChange={(d) => run(() => api.clock(d), {
          success: d ? { title: `Clock moved forward ${d} days` } : { title: "Clock back to real time" } })}
          options={[0, 7, 14, 30].map((d) => ({ value: d, label: d ? `+${d}d` : "Now" }))} />
      </div>
      <div className="pop-sep" />
      <Item Icon={Download} title="Export decisions" sub="CSV of every decision and approval"
        onClick={() => { onClose(); window.location.href = api.exportUrl; }} />
      <Item Icon={RotateCcw} title="Reset demo data" sub="Reseed all systems (debate cache is kept)" danger
        onClick={() => { if (window.confirm("Reset all demo data? Decisions and approvals are cleared.")) act(() => api.reset({}), { success: { title: "Demo data reset" } }); }} />
    </Popover>
  );
}

/* ------------------------------------------------------------------ command menu */
export function CommandMenu({ open, setOpen }) {
  const { decisions, run, theme, setTheme, stats } = useArbiter();
  const [deals, setDeals] = useState([]);
  useEffect(() => {
    const onKey = (e) => {
      if ((e.key === "k" || e.key === "K") && (e.metaKey || e.ctrlKey)) { e.preventDefault(); setOpen((o) => !o); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setOpen]);
  useEffect(() => { if (open) api.deals().then(setDeals).catch(() => {}); }, [open]);
  const go = (fn) => { setOpen(false); fn(); };
  const openItems = decisions.filter((d) => OPEN.has(d.status)).slice(0, 12);
  return (
    <Command.Dialog open={open} onOpenChange={setOpen} label="Command menu" className="cmdk-root">
      <div className="cmdk">
        <Command.Input placeholder="Search decisions, deals, pages or actions…" />
        <Command.List>
          <Command.Empty>No results.</Command.Empty>
          <Command.Group heading="Go to">
            {PAGES.map((p) => (
              <Command.Item key={p.key} value={`page ${p.label}`} onSelect={() => go(() => navigate(p.key))}>
                <p.Icon size={15} /> {p.label}
              </Command.Item>
            ))}
          </Command.Group>
          {openItems.length > 0 && (
            <Command.Group heading="Open decisions">
              {openItems.map((d) => (
                <Command.Item key={d.id} value={`decision ${d.deal_id} ${d.company} ${d.fields.join(" ")}`}
                  onSelect={() => go(() => navigate("review", d.id))}>
                  <Inbox size={15} /><span className="mono">{d.deal_id}</span> {d.company}
                  <span className="hint">{fieldList(d.fields)}</span>
                </Command.Item>
              ))}
            </Command.Group>
          )}
          <Command.Group heading="Deals">
            {deals.map((d) => (
              <Command.Item key={d.deal_id} value={`deal ${d.deal_id} ${d.company}`} onSelect={() => go(() => navigate("records", d.deal_id))}>
                <Database size={15} /><span className="mono">{d.deal_id}</span> {d.company}
                <span className="hint">{d.status}</span>
              </Command.Item>
            ))}
          </Command.Group>
          <Command.Group heading="Actions">
            <Command.Item value="action scan now" onSelect={() => go(() => run(api.scan, { success: { title: "Scan complete" } }))}>
              <RefreshCw size={15} /> Scan now
            </Command.Item>
            <Command.Item value="action inject drift" onSelect={() => go(() => run(() => api.inject({}), {
              success: (r) => ({ title: `Drift injected into ${r.deal_id}`, description: `${r.source}.${r.field}: ${r.old} → ${r.new}` }) }))}>
              <Zap size={15} /> Inject drift
            </Command.Item>
            {[7, 14, 30].map((d) => (
              <Command.Item key={d} value={`action clock fast forward ${d} days`} onSelect={() => go(() => run(() => api.clock(d)))}>
                <FastForward size={15} /> Fast-forward clock {d} days
              </Command.Item>
            ))}
            {stats?.clock_offset_days > 0 && (
              <Command.Item value="action clock reset now" onSelect={() => go(() => run(() => api.clock(0)))}>
                <FastForward size={15} /> Clock back to real time
              </Command.Item>
            )}
            <Command.Item value="action toggle theme" onSelect={() => go(() => setTheme(theme === "dark" ? "light" : "dark"))}>
              {theme === "dark" ? <Sun size={15} /> : <Moon size={15} />} Switch to {theme === "dark" ? "light" : "dark"} theme
            </Command.Item>
            <Command.Item value="action export csv" onSelect={() => go(() => { window.location.href = api.exportUrl; })}>
              <Download size={15} /> Export decisions (CSV)
            </Command.Item>
            <Command.Item value="action ask question" onSelect={() => go(() => navigate("ask"))}>
              <ArrowRight size={15} /> Ask a question
            </Command.Item>
          </Command.Group>
        </Command.List>
      </div>
    </Command.Dialog>
  );
}

export function MobileScrim({ open, onClose }) {
  return (
    <AnimatePresence>
      {open && (
        <motion.div className="scrim" style={{ zIndex: 54 }} onClick={onClose}
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }} />
      )}
    </AnimatePresence>
  );
}
