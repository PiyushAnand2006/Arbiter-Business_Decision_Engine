import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { api } from "./api.js";
import { OPEN, fieldList, setServerNow } from "./format.js";
import { navigate } from "./router.js";

const Ctx = createContext(null);
export const useArbiter = () => useContext(Ctx);

const read = (k, d) => {
  try {
    return localStorage.getItem(k) ?? d;
  } catch {
    return d;
  }
};
const write = (k, v) => {
  try {
    localStorage.setItem(k, v);
  } catch {
    /* storage unavailable: preferences just won't persist */
  }
};

export function ArbiterProvider({ children }) {
  const [stats, setStats] = useState(null);
  const [decisions, setDecisions] = useState([]);
  const [config, setConfig] = useState(null);
  const [activity, setActivity] = useState([]);
  const [health, setHealth] = useState([]);
  const [online, setOnline] = useState(true);
  const [tick, setTick] = useState(0);
  const [fresh, setFresh] = useState(() => new Set());
  const [actor, setActorState] = useState(() => read("arbiter.actor", ""));
  const [theme, setThemeState] = useState(() => document.documentElement.dataset.theme || "dark");
  const seen = useRef(null);
  const slow = useRef(0);

  const setActor = (v) => {
    setActorState(v);
    write("arbiter.actor", v);
  };
  const setTheme = (t) => {
    document.documentElement.dataset.theme = t;
    write("arbiter.theme", t);
    setThemeState(t);
  };

  const refresh = useCallback(async (full = false) => {
    try {
      const [s, d] = await Promise.all([api.stats(), api.decisions()]);
      setServerNow(s.now);
      setStats(s);
      setDecisions(d);
      setOnline(true);
      setTick((t) => t + 1);
      if (full || slow.current++ % 2 === 0) api.activity(40).then(setActivity).catch(() => {});
      if (full || slow.current % 4 === 0) api.health().then(setHealth).catch(() => {});

      const ids = new Set(d.map((x) => x.id));
      if (seen.current) {
        const added = d.filter((x) => !seen.current.has(x.id));
        if (added.length) {
          setFresh(new Set(added.map((x) => x.id)));
          setTimeout(() => setFresh(new Set()), 2400);
          added
            .filter((x) => x.origin === "scan")
            .slice(0, 3)
            .forEach((x) =>
              toast(`${x.reason === "stale" ? "Stale record" : "Conflict"} detected on ${x.deal_id}`, {
                description: `${x.company} · ${fieldList(x.fields)}`,
                action: { label: "Review", onClick: () => navigate("review", x.id) },
              })
            );
        }
      }
      seen.current = ids;
    } catch {
      setOnline(false);
    }
  }, []);

  useEffect(() => {
    api.config().then(setConfig).catch(() => {});
    refresh(true);
    const t = setInterval(() => refresh(false), 2500);
    return () => clearInterval(t);
  }, [refresh]);

  /** Run an action, toast failures, then refresh everything. */
  const run = useCallback(
    async (fn, { success, error = "Something went wrong" } = {}) => {
      try {
        const r = await fn();
        if (success) {
          const s = typeof success === "function" ? success(r) : success;
          if (s) toast.success(s.title || s, s.description ? { description: s.description } : undefined);
        }
        await refresh(true);
        return r;
      } catch (e) {
        toast.error(error, { description: e.message });
        return null;
      }
    },
    [refresh]
  );

  const openCount = useMemo(() => decisions.filter((d) => OPEN.has(d.status)).length, [decisions]);

  const value = {
    stats, decisions, config, activity, health, online, tick, fresh, openCount,
    actor, setActor, theme, setTheme, refresh, run,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
