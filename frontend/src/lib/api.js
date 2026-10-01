async function req(method, path, body) {
  const r = await fetch(`/api${path}`, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const d = data.detail;
    throw new Error(typeof d === "string" ? d : d ? JSON.stringify(d) : `Request failed (${r.status})`);
  }
  return data;
}

export const api = {
  stats: () => req("GET", "/stats"),
  config: () => req("GET", "/config"),
  decisions: () => req("GET", "/decisions?summary=true&limit=400"),
  decision: (id) => req("GET", `/decisions/${id}`),
  approve: (id, body) => req("POST", `/decisions/${id}/approve`, body),
  scan: () => req("POST", "/scan"),
  query: (q) => req("POST", "/query", { q }),
  priorities: () => req("GET", "/priorities"),
  deals: () => req("GET", "/deals"),
  deal: (id) => req("GET", `/deals/${id}`),
  activity: (limit = 40) => req("GET", `/activity?limit=${limit}`),
  health: () => req("GET", "/sources/health"),
  editSource: (s, id, body) => req("PATCH", `/sources/${s}/${id}`, body),
  inject: (body = {}) => req("POST", "/demo/inject", body),
  reset: (body = {}) => req("POST", "/demo/reset", body),
  clock: (d) => req("POST", "/demo/clock", { offset_days: d }),
  monitor: (enabled) => req("POST", "/demo/monitor", { enabled }),
  runEval: (live) => req("POST", "/eval/run", { live }),
  latestEval: () => req("GET", "/eval/latest"),
  exportUrl: "/api/export/decisions.csv",
};
