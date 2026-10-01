// The engine clock can be fast-forwarded (demo), so relative times are computed
// against the server's "now", tracked as a skew from the browser clock.
let skewMs = 0;
export const setServerNow = (iso) => {
  if (iso) skewMs = Date.parse(iso) - Date.now();
};
export const serverNow = () => Date.now() + skewMs;

export function ago(iso, { short = false } = {}) {
  if (!iso) return "—";
  const s = Math.max(0, (serverNow() - Date.parse(iso)) / 1000);
  if (s < 10) return "just now";
  if (s < 60) return `${Math.floor(s)}s${short ? "" : " ago"}`;
  if (s < 3600) return `${Math.floor(s / 60)}m${short ? "" : " ago"}`;
  if (s < 86400) return `${Math.floor(s / 3600)}h${short ? "" : " ago"}`;
  return `${Math.floor(s / 86400)}d${short ? "" : " ago"}`;
}

export function until(iso) {
  if (!iso) return null;
  const s = (Date.parse(iso) - serverNow()) / 1000;
  if (s <= 0) return null;
  if (s < 3600) return `${Math.ceil(s / 60)} min`;
  if (s < 86400) return `${Math.round(s / 3600)} h`;
  const d = Math.round(s / 86400);
  return `${d} day${d === 1 ? "" : "s"}`;
}

export const money = (v, { compact = false } = {}) => {
  if (v == null || Number.isNaN(v)) return "—";
  if (compact && Math.abs(v) >= 1000) {
    return `$${Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(v)}`;
  }
  return `$${Number(v).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
};
export const pct = (v, digits = 0) => (v == null ? "—" : `${(v * 100).toFixed(digits)}%`);
export const fix2 = (v) => (v == null ? "—" : Number(v).toFixed(2));
export const duration = (ms) => (ms == null ? "—" : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`);
export const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
export const initials = (name) =>
  (name || "").replace(/[^\p{L}\s]/gu, " ").split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0].toUpperCase()).join("") || "?";

export const FIELD = { stage: "Stage", value: "Value", close_date: "Close date", company: "Company", record: "Record" };
export const SOURCE = { crm: "CRM", finance: "Finance", pipeline: "Pipeline" };
export const SOURCES = ["crm", "finance", "pipeline"];
export const OPEN = new Set(["debating", "pending_approval", "needs_review"]);
export const APPROVABLE = new Set(["pending_approval", "needs_review"]);
export const fieldList = (fields) => fields.map((f) => FIELD[f] || f).join(", ");
