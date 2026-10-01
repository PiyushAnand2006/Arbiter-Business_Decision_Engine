import React, { useEffect, useState } from "react";
import { AnimatePresence, MotionConfig, motion } from "motion/react";
import { Toaster } from "sonner";
import { WifiOff } from "lucide-react";
import { CommandMenu, MobileScrim, PAGES, Sidebar, Topbar } from "./components/Shell.jsx";
import { EASE } from "./components/ui.jsx";
import { navigate, useRoute } from "./lib/router.js";
import { ArbiterProvider, useArbiter } from "./lib/store.jsx";
import Ask from "./pages/Ask.jsx";
import Engine from "./pages/Engine.jsx";
import Evaluation from "./pages/Evaluation.jsx";
import Followups from "./pages/Followups.jsx";
import Overview from "./pages/Overview.jsx";
import Records from "./pages/Records.jsx";
import Review from "./pages/Review.jsx";

class Boundary extends React.Component {
  state = { error: null };
  static getDerivedStateFromError(error) {
    return { error };
  }
  componentDidUpdate(prev) {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null });
  }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="placeholder" style={{ height: 320 }}>
        <div>
          <div className="ph-title">This view hit an error</div>
          <div className="small">{String(this.state.error.message || this.state.error)}</div>
          <button className="btn sm" style={{ marginTop: 12 }} onClick={() => this.setState({ error: null })}>Try again</button>
        </div>
      </div>
    );
  }
}

function Layout() {
  const { page, id } = useRoute();
  const { online, theme, decisions } = useArbiter();
  const [cmd, setCmd] = useState(false);
  const [nav, setNav] = useState(false);
  const known = PAGES.some((p) => p.key === page) ? page : "overview";
  const label = PAGES.find((p) => p.key === known).label;

  useEffect(() => {
    document.title = `${label} · Arbiter`;
  }, [label]);

  const crumbs = [{ label, onClick: id ? () => navigate(known) : undefined }];
  if (known === "review" && id) {
    const d = decisions.find((x) => String(x.id) === String(id));
    crumbs.push({ label: d ? `${d.deal_id} · ${d.company}` : `#${id}` });
  }
  if (known === "records" && id) crumbs.push({ label: id });

  const pageEl = {
    overview: <Overview />,
    review: <Review id={id} />,
    ask: <Ask />,
    records: <Records id={id} />,
    followups: <Followups />,
    evaluation: <Evaluation />,
    engine: <Engine />,
  }[known];

  return (
    <div className="shell">
      <Sidebar page={known} open={nav} onClose={() => setNav(false)} />
      <MobileScrim open={nav} onClose={() => setNav(false)} />
      <main className="main">
        <Topbar crumbs={crumbs} onMenu={() => setNav(true)} onCommand={() => setCmd(true)} />
        <AnimatePresence>
          {!online && (
            <motion.div initial={{ height: 0 }} animate={{ height: "auto" }} exit={{ height: 0 }} style={{ overflow: "hidden" }}>
              <div className="row small" style={{ padding: "8px 20px", background: "var(--critical-wash)", color: "var(--critical-text)" }}>
                <WifiOff size={14} /> Can't reach the Arbiter API - retrying. Start it with <span className="mono">python run.py</span>.
              </div>
            </motion.div>
          )}
        </AnimatePresence>
        <div className={`content ${known === "review" ? "fixed" : ""}`}>
          <AnimatePresence mode="wait" initial={false}>
            <motion.div key={known} style={{ height: known === "review" ? "100%" : undefined }}
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.14, ease: EASE }}>
              <Boundary resetKey={`${known}/${id}`}>{pageEl}</Boundary>
            </motion.div>
          </AnimatePresence>
        </div>
      </main>
      <CommandMenu open={cmd} setOpen={setCmd} />
      <Toaster theme={theme} position="bottom-right" closeButton
        toastOptions={{ style: { fontFamily: "var(--font)", fontSize: 13, borderRadius: 10 } }} />
    </div>
  );
}

export default function App() {
  return (
    <MotionConfig reducedMotion="user">
      <ArbiterProvider>
        <Layout />
      </ArbiterProvider>
    </MotionConfig>
  );
}
