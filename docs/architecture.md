# Arbiter — Architecture

## 1. System overview

```
                  ┌──────────────────────────────────────────────┐
                  │                  Dashboard (UI)              │
                  │  conflict feed · decision cards · approvals  │
                  └───────────────▲──────────────────────────────┘
                                  │ REST/JSON (+ polling or SSE)
                  ┌───────────────┴──────────────────────────────┐
                  │                FastAPI service               │
                  │  /scan /decisions /approve /demo/*           │
                  └───────┬───────────────┬───────────────┬──────┘
                          │               │               │
              ┌───────────▼─────┐  ┌──────▼───────┐ ┌─────▼────────────┐
              │  Engine (no LLM)│  │ Debate module│ │ Decision service │
              │ normalize       │  │ proponent    │ │ build card,      │
              │ agreement       │─▶│ challenger   │▶│ lineage,         │
              │ confidence      │  │ judge        │ │ counterfactual,  │
              │ gate            │  │ validator    │ │ approval state   │
              └───────────▲─────┘  └──────┬───────┘ └─────┬────────────┘
                          │               │ LLMClient      │
              ┌───────────┴─────┐         ▼ (real | mock)   │
              │  SQLite store   │◀───────────────────────────┘
              │ crm · finance · │
              │ pipeline · audit│
              │ conflicts · ... │
              └─────────────────┘
                          ▲
              ┌───────────┴─────┐
              │ Data generator  │  Faker + conflict/staleness injector (seeded)
              └─────────────────┘
```

**Core principle:** the expensive, non-deterministic part (LLM debate) sits *behind* a cheap, deterministic gate. Everything upstream of the gate is plain, unit-tested Python.

## 2. Tech stack

| Layer | Choice | Why |
|-------|--------|-----|
| Language | Python 3.11 | Team fluency, fast to build |
| API | FastAPI + Pydantic v2 | Typed schemas double as the team contract |
| Storage | SQLite (via SQLAlchemy or plain `sqlite3`) | Zero setup, portable, offline demo |
| Data gen | Faker + custom injector | Deterministic seeded conflicts |
| Debate orchestration | Small custom state machine (LangGraph optional) | 3 fixed steps; avoid framework overhead |
| LLM access | `LLMClient` interface: `ClaudeClient`, `GeminiClient`/other free-tier, `MockClient` | Swap providers, dev without quota |
| Frontend | React + Vite (or plain HTML/JS if faster) | Lightweight dashboard |
| Tests | pytest | Engine + validator must be tested |

## 3. Repository layout

```
arbiter/
├── docs/                    # prd.md, architecture.md, memory.md, rules.md, phases.md
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI app, router wiring
│   │   ├── config.py        # thresholds, weights, half-lives, budgets (single source)
│   │   ├── schemas.py       # Pydantic models = team contract
│   │   ├── db.py            # connection, migrations/create_all
│   │   ├── data/
│   │   │   ├── generator.py # Faker datasets
│   │   │   ├── injector.py  # conflicts + staleness, returns ground truth
│   │   │   └── seed.py      # CLI: seed / reset / inject
│   │   ├── engine/
│   │   │   ├── normalize.py # dates, currency, stage synonyms
│   │   │   ├── agreement.py # cross-source comparison
│   │   │   ├── confidence.py# freshness, correction rate, final score
│   │   │   └── gate.py      # DIRECT vs DEBATE routing
│   │   ├── agents/
│   │   │   ├── llm.py       # LLMClient + providers + retry + budget + cache
│   │   │   ├── prompts.py   # proponent / challenger / judge prompts
│   │   │   ├── debate.py    # orchestration
│   │   │   └── validate.py  # schema + citation validator
│   │   ├── services/
│   │   │   ├── decisions.py # decision card assembly, counterfactual
│   │   │   └── approvals.py # state machine + audit
│   │   └── api/
│   │       ├── scan.py
│   │       ├── decisions.py
│   │       └── demo.py      # inject-drift, reset
│   └── tests/
├── frontend/
│   └── src/                 # Feed, DecisionCard, EvidencePanel, ApprovalBar
├── data/                    # arbiter.db (gitignored), seeds
└── scripts/                 # run_all.sh, demo_reset.sh
```

## 4. Data model (SQLite)

```
crm_deals(deal_id PK, company, stage, value, owner, last_contacted, updated_at)
finance_records(deal_id PK, company, stage, value, invoice_status, updated_at)
pipeline_records(deal_id PK, company, stage, value, forecast_category, updated_at)

audit_log(id PK, source, deal_id, field, old_value, new_value, changed_at, changed_by)
   -- evidence for debates; also feeds correction-rate

conflicts(id PK, deal_id, field, sources_json, detected_at, status)
decisions(id PK, deal_id, query, path, answer_json, confidence, evidence_ids_json,
          counterfactual_json, status, created_at, expires_at)
debates(id PK, conflict_hash UNIQUE, transcript_json, verdict_json, llm_calls, created_at)
approvals(id PK, decision_id FK, action, actor, note, at)
```

- `deal_id` is the join key across all three systems.
- `conflict_hash = sha256(deal_id + field + sorted(source:value pairs))` → cache key; identical conflict never spends quota twice.
- `ground_truth` (used only in evaluation) lives in a separate table/file written by the injector and is **never** exposed to the engine or agents.

## 5. Engine (deterministic, no LLM)

### 5.1 Normalization
Canonicalize before comparing: ISO dates, numeric currency (strip `$`, commas, `K` suffix), lowercase stage synonyms mapped to a controlled vocabulary (`closed won` = `closed_won` = `won`). Tolerance for numerics (default ±0.5%) so rounding is not a conflict. Cosmetic differences must **not** trigger debate.

### 5.2 Agreement
For each `(deal_id, field)`, gather normalized values from every source that holds the field. `agreement = size_of_largest_agreeing_group / number_of_sources`. A field is **conflicted** if more than one distinct normalized value exists.

### 5.3 Confidence (per fact)

```
freshness   F = exp(-ln(2) * age_days / half_life[field])         # half_life from config
reliability R = 1 - min(0.5, corrections_last_90d / max(1, total_updates_last_90d))
agreement   A = agreement from 5.2 (0..1)

confidence  C = w_F*F + w_R*R + w_A*A        # default weights 0.4 / 0.2 / 0.4
```

- Half-lives (days, configurable): `stage` 14, `value` 30, `last_contacted` 7, `invoice_status` 21.
- Confidence is a pure function of stored data + `now`. No LLM input.
- Deal-level confidence for a query = min over the facts it depends on (weakest link).

### 5.4 Gate

```
if conflicted(fact):            route = DEBATE  (reason="conflict")
elif C < THRESH_LOW (0.60):     route = DEBATE  (reason="stale")   # or NEEDS_REVERIFY if budget exhausted
else:                           route = DIRECT
```

Budget guard: if session debate cap is reached, conflicts are queued and shown as `needs_review` with a rule-based provisional answer (most recent + highest-agreement source), clearly labelled provisional.

## 6. Debate module

### 6.1 Roles
1. **Proponent** — argues for value/source A using only supplied evidence.
2. **Challenger** — argues for value/source B (or "neither") using only supplied evidence.
3. **Judge** — reads both, returns verdict, reasoning, confidence label, and evidence IDs relied on.

### 6.2 Evidence packet (built by code, not the LLM)
```
{
  "deal_id": "D1042", "field": "stage",
  "candidates": [{"source":"crm","value":"closed_won","updated_at":"..."},
                 {"source":"finance","value":"open","updated_at":"..."}],
  "audit": [{"id":"A981","source":"crm","old":"negotiation","new":"closed_won","at":"...","by":"..."}, ...],
  "confidence_inputs": {"crm":{"F":0.9,"R":0.8}, "finance":{"F":0.4,"R":0.95}}
}
```
Agents receive only this packet. Each evidence item has an ID; agents must cite IDs.

### 6.3 Output schemas (Pydantic, strict JSON)
```
Argument: {position: str, claims: [{text, evidence_ids: [str]}], weaknesses_of_other_side: [str]}
Verdict:  {winner: "A"|"B"|"neither", resolved_value: str|null, reasoning: str,
           evidence_ids: [str], residual_uncertainty: str, needs_human_review: bool}
```

### 6.4 Validator (guardrail)
- JSON parses and matches schema; else retry once with a repair prompt; else fallback.
- Every cited `evidence_id` must exist in the packet. Invalid citation ⇒ verdict rejected ⇒ retry ⇒ fallback with `needs_human_review=true`.
- `resolved_value` must be one of the candidate values (or null with `winner="neither"`).

### 6.5 Cost controls
Max 3 calls per conflict; cache by `conflict_hash`; `MAX_DEBATES_PER_SESSION`; short prompts (packet only, no history); temperature low (≤0.2) for judge.

## 7. Decision service

Builds the **Decision Card**:

```
DecisionCard {
  id, deal_id, query,
  path: "direct" | "debate",
  answer: {field: value, ...},
  confidence: 0..1,
  confidence_breakdown: {F, R, A},
  evidence: [ {id, source, summary} ],          # lineage
  debate: {proponent_summary, challenger_summary, verdict} | null,
  counterfactual: {rejected_value, rejected_source, why_it_lost} | null,
  risk_hint: {value_at_stake, note} | null,      # P1
  expires_at, status: "pending_approval" | "approved" | "rejected" | "needs_review"
}
```

- **Counterfactual** is derived from the losing side's argument plus the judge's stated reason — it is not a separate LLM call.
- **Approval state machine:** `pending_approval → approved | rejected` (terminal). Approval writes to `approvals`. Only `approved` decisions render as "action taken".

## 8. API surface

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/scan` | Run engine over all deals; create/refresh conflicts and decisions |
| GET | `/decisions` | List cards (filters: status, path) |
| GET | `/decisions/{id}` | Full card with evidence and debate |
| POST | `/decisions/{id}/approve` | Human approval `{action, actor, note}` |
| POST | `/query` | Natural-language-ish query for a deal (`"status of D1042"`) → card |
| GET | `/stats` | Counts: direct vs debate, conflicts, LLM calls used, cache hits |
| POST | `/demo/inject` | Introduce a controlled drift on a chosen deal/field |
| POST | `/demo/reset` | Reseed dataset to baseline |

Queries in v1 are parsed by simple rules (deal-ID regex + intent keywords) — no LLM needed to route.

## 9. Frontend

- **Live feed:** newest conflicts/decisions, colour-coded `direct` vs `debate`.
- **Decision card view:** answer, confidence gauge with F/R/A breakdown, evidence list, debate panel (proponent vs challenger side-by-side), counterfactual box, approve/reject bar.
- **Stats strip:** direct vs debate counts, LLM calls used vs cap.
- **Demo panel:** Inject drift / Reset buttons.
- Poll `/decisions` every 2–3 s (SSE only if time allows).

## 10. Configuration (single file: `config.py` / `.env`)

```
HALF_LIFE_DAYS = {stage:14, value:30, last_contacted:7, invoice_status:21}
WEIGHTS = {F:0.4, R:0.2, A:0.4}
THRESH_LOW = 0.60
NUMERIC_TOLERANCE = 0.005
MAX_DEBATES_PER_SESSION = 25
LLM_PROVIDER = mock | claude | gemini
LLM_MODEL = ...
LLM_TEMPERATURE_JUDGE = 0.2
SEED = 42
```

## 11. Failure modes and handling

| Failure | Behaviour |
|---------|-----------|
| LLM timeout / rate limit | Retry once with backoff → fallback verdict (`needs_human_review`) |
| Invalid JSON / bad citations | Repair retry once → fallback |
| Quota cap reached | Queue conflicts as `needs_review` with provisional rule-based answer |
| Empty audit log for a conflict | Judge instructed to say "insufficient evidence" → `winner="neither"`, escalate |
| DB corrupted during demo | `/demo/reset` reseeds in < 2 s |

## 12. Testing strategy

- **Unit:** normalizer edge cases, confidence math (freshness monotonic decay, bounds 0..1), agreement, gate routing table.
- **Property:** cosmetic-only differences never produce `DEBATE`.
- **Validator:** hallucinated evidence ID rejected; malformed JSON repaired or fallback.
- **Integration:** seeded dataset → `/scan` → expected number of conflicts equals injector ground truth.
- **Evaluation script:** computes recall, false-conflict rate, reconciliation accuracy against `ground_truth` (feeds the evaluation slide).
- **Mock LLM:** deterministic responses so CI and dev cost zero quota.
