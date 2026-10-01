# Design decisions & deviations from the PRD / architecture

The build follows `prd.md` and `architecture.md`. Where the documents were ambiguous, internally inconsistent, or
could be improved toward the goal, this log records what changed and why.

## Confidence engine

**1. Weights are `F 0.5 / R 0.15 / A 0.35`, not `0.4 / 0.2 / 0.4`.**
With the draft weights, a fact that every system agrees on (A = 1) with a clean history (R = 1) scores at least
`0.2 + 0.4 = 0.60` however stale it is, so it can never fall below the 0.60 threshold. Scenario S3 (a deal untouched
for 70 days) could therefore never trigger. With the new weights, the floor for agreeing, reliable data is 0.50:

| Fact | Age | Confidence | Route |
|---|---|---|---|
| stage (half-life 14 days) | 10 days | ≈ 0.79 | direct |
| stage | 70 days | ≈ 0.51 | stale → debate |
| value (half-life 30 days) | 70 days | ≈ 0.59 | stale → debate |

The weights stay in `config.py` / `.env`, and the dashboard shows the live formula.

**2. Fact-level F and R come from the winning (largest) group.** F is the freshest confirmation in that group and R is
the group's mean reliability. The confidence of a *resolved* conflict is computed for the chosen side, so a minority
winner honestly scores lower (A = 1/3) even when the judge is sure. The LLM never sets confidence.

**3. Reliability counts `arbiter_sync` as a correction.** When a human approves a decision that overwrites a source,
that source's correction rate rises. Sources that are often wrong become less trusted over time.

**4. Sunset timer = validity window − current age.** The validity window solves `C(t) = threshold` for a
just-verified fact. Subtracting the current age of the supporting record gives the time left. Stale answers are
therefore expired on arrival, and approval (which re-syncs or re-confirms the record) restarts the timer.

## Data

**5. `close_date` is a fourth shared field.** It exercises date normalization (ISO vs `MM/DD/YYYY` vs `DD Mon YYYY`)
and supports the "slipped close date" conflicts. The architecture's fields (`owner`, `last_contacted`,
`invoice_status`, `forecast_category`) are kept as single-source context evidence.

**6. Finance stage labels read `Open - Negotiation` / `Closed - Won`.** This mirrors the PRD's "finance says *open*"
while still mapping to the fine-grained stage vocabulary, so finance and CRM are compared like for like.

**7. Injected patterns are chosen so that the truth is recoverable from evidence, and so that simple rules fail on
some of them.** There are 13 patterns: stale majority, bot overwrite, typos (an extra zero, transposed digits, day and
month swapped), an authoritative billing value, a pipeline-only date slip, open-but-stale records, and a
closed-but-old record that should hold. The ground truth goes to a separate file that the engine and agents never
read.

## Debate

**8. Calls per conflict: 3 on the happy path, at most 4.** The PRD asks for both "≤ 3 LLM calls per conflict" and
"retry once on invalid output". Arbiter allows **one** repair retry per conflict, shared across roles. A debater that
still fails is replaced by an evidence-only summary, and a judge that still fails yields the rule-based fallback
flagged `needs_human_review`. The measured average is 3.0.

**9. Proponent and challenger run in parallel** (they argue from the same packet and know the other side's
position), then the judge runs. That is two sequential round-trips instead of three, which helps the < 20 s target.

**10. Stale facts of one deal are debated together** (one "does this record still hold, or must it be
re-verified?" debate per deal), not one debate per field. This matches how people reason about stale records and
keeps the first scan at 19 debates, inside the default budget of 25.

**11. One decision card per deal**, covering every flagged fact of that deal (for D1042, stage and value together),
with one debate and one counterfactual per fact. Approval is per card.

**12. Claude provider details.** It uses structured outputs (`output_config.format`) with a per-packet JSON schema in
which evidence IDs and resolved values are **enums**, so citation validity is enforced at decode time as well as by
the validator. Current Claude models do not accept `temperature`, so `LLM_EFFORT` controls depth instead
(`LLM_TEMPERATURE_JUDGE` applies to Gemini). Server-side refusal fallbacks are enabled. The default model is
`claude-opus-5-5`; override it with `LLM_MODEL`.

**13. The mock provider is a heuristic reasoner, not canned text.** It weighs the same signals the judge prompt
describes, so the offline demo produces sensible, varied verdicts. It is labelled as a mock everywhere, including in
the evaluation report.

## Product

**14. Approval "action" = sync the synthetic sources** to the chosen value, with an audit entry per changed field.
This closes the loop in the demo: approve → the conflict disappears on the next scan. Stale "re-verify" verdicts
create a follow-up task and change no data.

**15. Demo additions:** a **live-edit Sources tab** covers S4 without Google Sheets, a **clock fast-forward** shows
objective confidence decay live, and a **background monitor** re-scans every 4 s. The debate cache survives resets,
so rehearsing the demo costs no quota.

**16. Statuses beyond the architecture:** `debating` (verdict pending), `superseded` (another approval resolved the
same facts), and `informational` (a direct answer with nothing to execute).

**17. API routes live under `/api`,** so the built dashboard can be served from `/` on the same origin.

## Round 2: UI redesign + research-driven features

**18. The dashboard is rebuilt as a product, not a demo page.** It is organized around the job (see the state →
review what needs you → drill into data): a sidebar app shell, an inbox-style Review workspace with tabs, a Records
explorer with an edit drawer, and a ⌘K command menu. Demo controls moved into one **Demo** menu. The decorative
pixel strip, the display serif, emoji buttons and explanatory copy on every panel were removed. There is one UI sans
(Inter), light and dark themes, and Motion transitions (page fade, shared tab and nav indicators, animated queue
reordering, drawer slide, number tickers) that respect `prefers-reduced-motion`.

**19. The chart palette is validated, not eyeballed.** Direct / conflict / stale use blue / orange / violet steps
that pass the dataviz validator in both themes (worst adjacent CVD ΔE 24.7 light, 26.0 dark). Status (awaiting,
needs review, approved) uses the fixed status palette, always with an icon and a label. Charts are hand-rolled SVG
with 2px surface gaps, hover tooltips, and a legend that doubles as the table view.

**20. Discrepancy taxonomy is deterministic** (`engine/classify.py`). The LLM debate decides *which* value is right.
The label (lagging system, entry error, automated overwrite, authoritative update, unexplained, stale record) comes
from rules over the same evidence packet, so triage never depends on the model.

**21. The position-swap check is limited to high stakes** (`CONSISTENCY_CHECK_MIN_STAKE`, default $100k expected
revenue). Standard conflicts still cost exactly 3 calls. Five of the 15 seeded conflicts qualify for the extra
re-judge, so the average is 3.26 calls per debate. A flip under swapping sets `needs_human_review`.

**22. The risk hint is priced from the whole deal**, not just the flagged facts. A value-only conflict now uses the
deal's real stage probability, and a stage-only conflict now has a value at stake. Before this fix, both were
under-priced.

**23. Asking about a deal reuses its open decision** when the same conflicts are already in review, so the queue
never holds duplicates. Overlapping decisions created independently are still superseded on approval.

**24. Live debate progress.** The debate reports its stage (arguing → judging → verifying), which the workspace shows
as a stepper. It is real backend state (`card.progress`), not an animation on a timer.
