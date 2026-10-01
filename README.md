# Arbiter

**Only debates when your business data actually disagrees.**

Arbiter is an AI decision engine for business data (BFWAI/HACK 26 · PS-04 · Team Aviator). It scores how
trustworthy every business fact is from **staleness, cross-system agreement and correction history** — never from an
LLM's self-assessment — and only triggers a structured **proponent / challenger / judge** debate when the data
genuinely conflicts or has decayed. Every decision comes with its evidence lineage, an objective confidence score, the
**rejected counter-argument**, and waits for a **human to approve** it.

- Idea deck: `Arbiter - PS-04 Idea Submission.pdf` · PRD: [docs/prd.md](docs/prd.md) · Architecture: [docs/architecture.md](docs/architecture.md)
- What changed from those docs, and why: [docs/decisions.md](docs/decisions.md)
- A 4-minute live demo script: [docs/demo-script.md](docs/demo-script.md)

---

## Quick start (one command)

Requirements: Python 3.11+ and Node 18+ (Node is only needed to build the dashboard once).

```bash
python run.py
```

Then open **http://localhost:8000**. The first run creates `.venv`, installs the backend, builds the dashboard, seeds
50 synthetic deals across three systems, and starts a background monitor. Everything runs locally on SQLite with the
**mock provider** — no API key and no network needed.

```bash
python run.py --reset      # reseed demo data before starting
python run.py --build      # force a dashboard rebuild
```

### Use a real LLM for the debate

```bash
cp .env.example .env       # then edit:
LLM_PROVIDER=claude        # or gemini
ANTHROPIC_API_KEY=...      # or GEMINI_API_KEY=...
```

- **Claude** (`claude-opus-5-5` by default) uses the Anthropic SDK with **structured outputs**: each request's JSON
  schema is built from the evidence packet, so evidence IDs and resolved values are enums the model cannot step
  outside of. Depth is set with `LLM_EFFORT` (current Claude models take no temperature), and server-side refusal
  fallbacks are enabled.
- **Gemini** (`gemini-2.5-flash` by default) uses the REST API with JSON mode and the judge temperature from `.env`.
- Every provider's output still goes through the same validator (schema, citation, and value checks).

---

## How it works

```
 CRM ─┐                                   ┌─ DIRECT ── answer instantly (no LLM)
 Finance ─┼─ normalize ─ agree ─ score ─ GATE ┤
 Pipeline ┘   (rules)   (rules)  (rules)  └─ DEBATE ── proponent ∥ challenger → judge → validator
                                                            │
                                   decision card: answer · confidence · evidence · counterfactual
                                                            │
                                               human approves / rejects → sync + audit
```

| Stage | What happens | LLM? |
|---|---|---|
| **Normalize** | `"Closed Won"` = `"Closed - Won"` = `"closed-won"`; `48000` = `$48,000.00` = `48K` (±0.5%); `2026-10-15` = `10/15/2026` = `15 Oct 2026`; company casing and suffixes. | no |
| **Agree** | Groups equal values across systems. `A = largest group / sources`. Conflicted if more than one distinct value. | no |
| **Score** | `F = exp(−ln2·age/half_life[field])`, `R = 1 − min(0.5, corrections_90d / updates_90d)`, **`C = 0.5·F + 0.15·R + 0.35·A`** | no |
| **Gate** | conflict → debate · `C < 0.60` → stale → debate · else → direct. Budget spent → provisional rule-based answer. | no |
| **Debate** | Code builds an evidence packet (records, audit log, context, each with an ID). Proponent and challenger argue in parallel; the judge rules and must cite real IDs. | **yes** |
| **Validate** | JSON schema, no extra keys (so no LLM "confidence"), cited IDs must exist, resolved value must be the winner's value. One repair retry, then a rule-based fallback flagged `needs_human_review`. | no |
| **Card** | Answer, **objective** confidence of the chosen value (F/R/A breakdown), evidence lineage with cited items, debate transcript, **counterfactual** (what lost and why), cost-of-being-wrong, sunset timer. | no |
| **Approve** | `pending → approved / rejected`. Approval syncs the losing systems to the chosen value with an `arbiter_sync` audit entry, which also lowers that source's reliability score. | no |

**Cost controls:** clean data never calls an LLM; 3 calls per conflict (plus at most one repair retry); debates are
cached by `sha256(deal + field + source values)`, so an identical conflict is never paid for twice (the cache survives
demo resets); session cap of 25 debates, after which answers are provisional.

---

## Evaluation (PRD §7)

`python -m app.services.evaluation` (from `backend/`), or the **Evaluation** tab. The command seeds a throwaway copy
of the dataset with known injected problems, runs everything end to end, and compares the output with ground truth
that the engine and agents never see. The baseline applies "majority, then most recent" to the **same** evidence.

| Metric | Target | Result (mock provider) |
|---|---|---|
| Conflict detection recall | ≥ 95% | **100%** (15/15) |
| False-conflict rate (cosmetic differences) | ≤ 5% | **0%** |
| Reconciliation accuracy vs ground truth | ≥ 80% | **100%** (baseline: 68%) |
| Debate rate on clean records | 0% | **0%** (177 of 200 facts answered directly) |
| Citation validity | 100% | **100%** (enforced by the validator) |
| Time from conflict to decision card | < 1 min | **< 0.3 s** mock (a live model adds two sequential LLM rounds - not yet measured) |
| LLM calls per conflict | ≤ 3 | **3.0** (+1 swap re-judge on the 5 high-stakes conflicts) |

> **Honesty note:** the mock provider is a deterministic, evidence-weighing reasoner. It reads only the packet, but
> it was written by the same people who wrote the injector, so its 100% accuracy is **not** a model result. Run
> `python -m app.services.evaluation --live` with Claude or Gemini configured to get model numbers (about 60 calls;
> debates already cached in the demo DB are reused). Detection recall, the false-conflict rate and the clean-debate
> rate come from the rule engine and do not depend on the provider.

The baseline gets these wrong, and the debate gets them right: a **stale majority** (CRM advanced the stage, but
finance and pipeline are old copies), an **authoritative minority** (billing issued the invoice at a different
amount), a finance **deal-lost** update with a voided invoice, a **pipeline-only** date slip, and a closed-and-paid
record that is merely old.

---

## The dashboard

A product-grade React app (Inter, light + dark themes, Motion transitions, keyboard-first review). The flow follows
the job: **see the state → review what needs you → drill into the data**.

| Page | What it's for |
|---|---|
| **Overview** | KPIs (facts monitored, % answered directly, open decisions with a live trend, LLM usage), the gate chart (direct / conflict / stale), discrepancy mix, *Needs attention* ranked by exposure, **source-health scorecards**, review analytics and the **activity timeline**. |
| **Review** | Inbox-style queue (open / resolved, sort by exposure, filter) + decision workspace: **Summary** (resolution vs every system, objective confidence with a **decay projection**, cost of being wrong, *why not X?*), **Debate** (proponent vs challenger, judge ruling, citation + position-swap checks), **Evidence**, **History**. Approve with `A`, reject with `R`, move with `J`/`K`; the queue auto-advances after each decision. |
| **Ask** | Rule-routed questions (S1, S2, S3, S5 built in). Asking about a deal that already has an open decision reuses it - no duplicates. |
| **Records** | Golden record per deal with per-system agreement; open any deal in a drawer and **live-edit** a system's value (S4) - the monitor catches it within seconds. |
| **Follow-ups** | S5 ranked list; deals with conflicting or stale facts are listed separately instead of being ranked silently. |
| **Evaluation / Engine** | PRD metrics vs targets, Arbiter vs baseline, cost; the pipeline, formula and live parameters. |

**Everywhere:** `Ctrl/⌘ K` command menu (jump to any decision, deal or page; run any action) · **Demo** menu
(scan, inject drift, fast-forward the engine clock, export CSV, reset) · live toasts when the monitor finds something.

## Features adopted from similar projects

Researched on GitHub; each is implemented, tested and visible in the UI.

| Feature | Inspired by | In Arbiter |
|---|---|---|
| **Discrepancy taxonomy + severity** | [multi-system-reconciliation-agent](https://github.com/kareembrantley-lab/multi-system-reconciliation-agent), [agentic-financial-reconciliation](https://github.com/chanupadeshan/agentic-financial-reconciliation) | Every conflict is classified deterministically (lagging system, entry error, automated overwrite, authoritative update, unexplained, stale record) and graded high / medium / low from revenue at stake. |
| **Position-swap judge check** | [Awesome-LLM-as-a-judge](https://github.com/llm-as-a-judge/Awesome-LLM-as-a-judge) (position bias, swap operation), [llm-committee](https://github.com/chenmoneygithub/llm-committee) (measurable disagreement) | High-stakes conflicts are re-judged with sides A/B swapped; if the verdict flips, it's escalated to a human. This is the PRD's P2 "second judge" stretch goal. |
| **Evidence-cited judging + verification** | [multi-agent-debate](https://github.com/salismt/multi-agent-debate) | Judges must cite packet IDs (enforced by the validator, and by enum schemas on Claude); the UI shows each check that passed. |
| **Source trust scorecards** | truth discovery ([truthdiscovery](https://github.com/joesingo/truthdiscovery), [spectrum](https://github.com/totucuong/spectrum)) | Per system: agreement rate, reliability, median age, outlier facts, debates lost, corrections - `GET /api/sources/health`. |
| **Trend + decision analytics** | reconciliation trend charts; review-rate / latency metrics | Open-issue trend, approval rate, flagged-for-review rate, median time to human decision. |
| **Activity timeline, export, alerts** | observability tools ([Elementary](https://github.com/elementary-data/elementary) Slack alerts), n8n reconciliation workflow | `GET /api/activity`, `GET /api/export/decisions.csv`, and an optional Slack-compatible webhook (`ALERT_WEBHOOK_URL`) for high-severity verdicts. |

Also considered but not built (good next steps): claim tags (fact / inference / assumption) in the evidence ledger,
a "request more evidence" reviewer action, iterative truth-discovery weights feeding the confidence formula, and
multi-round debates.

---

## Project layout

```
run.py                      one-command launcher
backend/
  app/config.py             every threshold, weight, half-life and budget (single source)
  app/schemas.py            Pydantic contract (cards, verdicts, requests)
  app/db.py                 SQLite store (all SQL lives here)
  app/data/                 generator (Faker, seeded) · injector (conflicts + ground truth) · seed CLI
  app/engine/               normalize · agreement · confidence · gate · assess · classify   ← pure, no LLM, no I/O
  app/agents/               llm (Claude/Gemini/Mock + budget) · prompts · packet · debate · validate · mock_reasoner
  app/services/             arbiter (scan/resolve/query) · decisions (card) · approvals · evaluation
  app/api/                  FastAPI routes under /api
  tests/                    129 tests: unit, property, validator, integration, API, features, eval
frontend/src/
  lib/                      api client · store (polling, actions) · hash router · formatting
  components/               app shell + ⌘K menu · UI primitives · hand-rolled SVG charts
  pages/                    Overview · Review + DecisionView · Ask · Records · Follow-ups · Evaluation · Engine
  styles/                   design tokens (light/dark, validated chart palette) · components
docs/                       prd.md · architecture.md · decisions.md · demo-script.md
data/                       arbiter.db, ground_truth.json, eval_report.json (generated, gitignored)
```

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/scan` | Run the engine over all deals; create or refresh conflicts and decision cards |
| GET | `/api/decisions` | List cards (`status`, `path`, `deal_id`, `summary=true`) |
| GET | `/api/decisions/{id}` | Full card with evidence and debate |
| POST | `/api/decisions/{id}/approve` | `{action: approve\|reject, actor, note}` |
| POST | `/api/query` | `{"q": "status and value of D1042"}` → card, or the priority list |
| GET | `/api/priorities` | S5 ranked follow-up list |
| GET | `/api/stats` | Direct vs debate, LLM calls, cache hits, budget, trend history, review analytics |
| GET | `/api/deals`, `/api/deals/{id}` | Per-deal facts, confidence, outlier systems, audit log |
| GET | `/api/activity` | Event timeline (detections, verdicts, approvals, edits, drift) |
| GET | `/api/sources/health` | Per-system scorecards |
| GET | `/api/export/decisions.csv` | Every decision and approval as CSV |
| GET/PATCH | `/api/sources/{source}[/{deal_id}]` | View or live-edit a system of record |
| POST | `/api/demo/inject`, `/api/demo/reset`, `/api/demo/clock`, `/api/demo/monitor` | Demo controls |
| POST/GET | `/api/eval/run`, `/api/eval/latest` | Evaluation |

Interactive docs: http://localhost:8000/docs

## Tests

```bash
cd backend
../.venv/Scripts/python -m pytest -q      # Windows  (../.venv/bin/python on macOS/Linux)
```

## Safety

Synthetic data only; no real customers, no OAuth, and no writes to real CRMs. No action executes without a named
human approving it, and every approval is logged. There are no secrets in the repo: keys live in `.env`, which is
gitignored.
