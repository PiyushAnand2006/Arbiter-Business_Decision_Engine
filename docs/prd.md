# Arbiter — Product Requirements Document (PRD)

**Hackathon:** AI Build Challenge 2026 (BFWAI/HACK 26) · **Track:** PS-04 — AI Decision Engine for Business Data
**Build window:** 3 days · **Team:** 3 members · **Status:** Pre-build

---

## 1. One-line pitch

Arbiter is an AI decision engine that scores how trustworthy every business fact is (from staleness and cross-system agreement, never from an LLM's self-assessment) and only triggers a structured agent debate when the data genuinely disagrees — producing a decision, its evidence trail, and the rejected counter-argument, for a human to approve.

## 2. Problem

Business data (CRM records, finance sheets, pipeline trackers) drifts out of sync. A deal is "closed-won" in the CRM but "open" in finance; a value differs by $5K between systems. Teams either trust one source blindly or burn hours cross-checking by hand, and decisions get made on stale or conflicting numbers.

**Persona:** Revenue / Sales-Ops lead at a mid-size B2B company (fictional: "Northwind Systems") who must decide which deals to act on and needs to trust the numbers behind each call.

**Cost today:** ~25 minutes of manual cross-checking per contested decision; silent contradictions reach decision-makers when the check is skipped.

## 3. Goals and non-goals

### Goals
1. Detect cross-system conflicts and stale facts automatically, using objective (non-LLM) signals.
2. Resolve genuine conflicts with a structured debate (proponent / challenger / judge) that cites real evidence records.
3. Show a full evidence lineage, a confidence score, and the rejected alternative (counterfactual) for every decision.
4. Require explicit human approval before any action is marked taken.
5. Spend LLM quota only where the data is actually disputed (confidence-gated debate).

### Non-goals (explicitly out of scope)
- Voice input/output.
- Document parsing (Docling / PDF ingestion).
- Real customer data, real OAuth integrations, or writing back to real CRMs.
- Autonomous execution of business actions.
- Generic lead-scoring / "rank leads and explain why" as the headline feature (crowded space).
- Multi-tenant auth, billing, deployment at scale.

## 4. Users and core scenarios

| # | Scenario | Expected behaviour |
|---|----------|--------------------|
| S1 | **Clean case.** User asks "What is the status and value of deal D1007?" — all sources agree and are fresh. | Instant answer, high confidence, **no debate triggered**. |
| S2 | **Conflict case.** CRM says D1042 is `closed_won` at $48,000; finance says `open` at $45,000. | Debate triggered. Judge reconciles, cites audit-log evidence. Decision card shows verdict + losing argument. Human approves. |
| S3 | **Stale case.** D1019 was last updated 70 days ago; no conflict but confidence has decayed below threshold. | Flagged as low-confidence; debate (or "needs re-verification" verdict) triggered. |
| S4 | **Live-edit demo.** Presenter edits a value in one source; engine catches it on next scan. | New conflict appears on dashboard within seconds. |
| S5 | **Priority list (stretch).** "Which open deals should we follow up on first?" | Ranked list where each item carries confidence + evidence; low-confidence items are flagged rather than silently ranked. |

## 5. Functional requirements

### P0 — must ship
- **FR-1 Data layer:** three synthetic systems of record (CRM, Finance, Pipeline tracker) with overlapping deal IDs and a change/audit log; seeded deterministically with injected conflicts and stale records.
- **FR-2 Normalizer:** rule-based normalization so cosmetic differences are not treated as conflicts (date formats, currency formatting, stage synonyms, casing).
- **FR-3 Confidence engine:** per-fact score in [0,1] computed from freshness (field-specific half-life), historical correction rate, and cross-source agreement. No LLM calls.
- **FR-4 Gate:** routes each fact/query to `DIRECT` (no debate) or `DEBATE` using conflict detection and a configurable confidence threshold.
- **FR-5 Debate engine:** proponent (side A), challenger (side B), judge. All outputs are schema-validated JSON. Judge must cite evidence IDs that exist in the provided evidence set.
- **FR-6 Decision card:** answer, confidence, evidence lineage (record + audit IDs), debate transcript summary, counterfactual (losing argument and why it lost), status.
- **FR-7 Human approval:** `pending → approved | rejected`; nothing is marked "taken" without approval; every approval is logged.
- **FR-8 Dashboard:** live conflict feed, per-decision detail with evidence and counterfactual, and a visible split of "skipped debate" vs "triggered debate".
- **FR-9 Demo controls:** "Inject drift" button/endpoint and "Reset data" to make the demo repeatable.

### P1 — should ship if on schedule
- **FR-10 Cost-of-being-wrong hint:** show asymmetric risk (deal value × probability) next to confidence to prioritize which conflicts a human reviews first.
- **FR-11 Sunset timers:** each decision shows a validity window based on field volatility; expired decisions show "re-verify".
- **FR-12 Priority list (S5).**

### P2 — stretch
- Google Sheets as a live source for the live-edit demo moment.
- Judge-vs-second-judge disagreement check on high-value conflicts.

## 6. Non-functional requirements

| Area | Requirement |
|------|-------------|
| **Quota** | Debate costs ≤ 3 LLM calls per conflict. Cache by conflict hash. Global per-session cap (default 25 debates). Clean data never calls an LLM. |
| **Latency** | Scan of full dataset < 2 s. Debate resolution < 20 s per conflict. |
| **Determinism** | Same seed ⇒ same dataset and same injected conflicts. Scoring engine is pure and unit-testable. |
| **Reliability** | If the LLM fails or returns invalid JSON: retry once, then fall back to a rule-based verdict flagged `needs_human_review`. Never crash the dashboard. |
| **Auditability** | Every decision stores inputs, scores, prompts' evidence IDs, outputs, and approver action. |
| **Safety** | No auto-execution. Synthetic data only. No secrets in the repo. |

## 7. Success metrics (evaluation slide)

Measured on a synthetic set of ~50 deals with a known ground truth of injected conflicts:

| Metric | Target |
|--------|--------|
| Conflict detection recall | ≥ 95% |
| False-conflict rate (cosmetic differences flagged) | ≤ 5% |
| Reconciliation accuracy vs ground truth | ≥ 80% |
| Debate rate on clean records | 0% |
| Time from conflict to decision card | < 1 min (vs ~25 min manual baseline) |
| Citation validity (judge cites only real evidence IDs) | 100% (enforced by validator) |

## 8. Differentiation (what to say to judges)

Most "AI decision engine" builds either rank records with an LLM explanation (crowded) or debate indiscriminately (expensive, and multi-agent debate itself is a well-known pattern). Arbiter's angle is **when and why** it argues:
1. Confidence is objective (staleness + agreement + correction history), not LLM self-reported.
2. Debate fires **only** on real, evidence-backed cross-system disagreement or decayed confidence.
3. The losing argument is preserved as the counterfactual explanation.
4. A human always approves.

> Caveat for honesty in Q&A: novelty is in the specific combination and gating, not in any single component. Do not claim to have invented agent debate.

## 9. Assumptions and risks

| Risk | Mitigation |
|------|------------|
| Free-tier LLM quota exhausted mid-demo | Mock LLM provider for dev; cache debates; pre-warm demo conflicts; rule-based fallback verdict. |
| LLM returns malformed / hallucinated citations | JSON schema validation + citation validator; retry once; fallback. |
| Scope creep into P1/P2 | Phase exit criteria in `phases.md`; cut list defined. |
| Demo depends on live network | Everything runs locally on SQLite; Sheets integration is optional stretch only. |
| Confidence weights feel arbitrary to judges | Document the formula, show it on the dashboard, keep weights in one config file. |

## 10. Deliverables

1. Working local app (backend + dashboard) runnable with one command.
2. Seeded synthetic dataset + reset/inject tools.
3. Idea deck (`Arbiter - PS-04 Idea Submission.pptx`).
4. Rehearsed 3–5 minute live demo script (see `phases.md`).
5. Public post (LinkedIn/X) and builder pass card.
