# Live demo script (~4 minutes)

**Before going on stage:** run `python run.py` and open http://localhost:8000. Choose **Demo → Reset demo data** and
wait about 10 seconds for the first debates to finish. Debates are cached, so every rehearsal after the first costs
zero LLM calls. Click your name at the bottom of the sidebar and set it once; approvals are logged under it.

Keyboard: `Ctrl/⌘ K` opens the command menu. In Review: `J`/`K` move, `A` approves, `R` rejects.

---

### 0:00 · Overview: the state of the data (30 s)
> "Northwind's CRM, finance and pipeline systems drift apart. Today someone spends about 25 minutes cross-checking
> before every decision. Arbiter watches all three continuously."

Point at **Answered directly: 88.5%**, then at the routing chart: 177 facts blue (direct), 15 orange (conflict),
8 violet (stale). *"Only the orange and violet ever reach an AI."* Then **Discrepancy types**, **Needs attention**
(ranked by money at risk) and **Source health**: Finance is the system that is usually behind.

### 0:30 · S1: clean data costs nothing (20 s)
**Ask** → *What is the status and value of deal D1007?* It is answered directly with no LLM call, and the LLM-usage
tile doesn't move.

### 0:50 · S2: a real conflict (90 s)
**Review** → select **D1042 · Bryant-Hickman**.
1. **Resolution:** CRM and Pipeline say *Closed Won, $48,000*; Finance (✗) still says *Open - Negotiation, $45,000*.
   Tag: **Lagging system**.
2. **Objective confidence 0.85**, with the decay projection: *"This number comes from freshness, correction history
   and agreement. The model never sets it. The dashed line shows when this answer goes stale."*
3. **Why not $45,000?** Finance's record is a stale copy from before the rep's change two days ago.
4. **Debate** tab: proponent and challenger cite evidence IDs (hover an ID to see what it is). The judge relied on
   audit entry `A0856`. Below it are the checks: all citations exist in the packet, and on high-stakes conflicts the
   **position-swap check** re-judges with the sides swapped.
5. Press **A**. *"Nothing happens until a person approves. Now Finance is synced, with an audit entry."* The queue
   moves straight to the next item.

### 2:20 · S3: stale data decays objectively (30 s)
Open **D1019** from the queue (tag **Stale record**). Confidence is **0.51**, below the 0.60 line on the decay
chart, even though all three systems agree: nobody has touched the deal in 70 days. The recommendation is
*re-verify*.
> Optional: **Demo → Engine clock +30d**, then watch the Overview routing chart shift toward stale. Set it back to
> **Now**.

### 2:50 · S4: live drift is caught within seconds (30 s)
**Records** → open **D1007** → in the **Finance** column, click the value (`$121,900.00`) and type
`$1,219,000.00` (one extra zero), then press Enter. Within about 4 seconds a toast says *"Conflict detected on
D1007"*. Click **Review**: it is tagged **Entry error**, and the judge keeps $121,900 because the Finance value is
*"~10× the other systems' value, a likely extra zero"*. (**Demo → Inject drift** does the same without typing.)

### 3:20 · S5 + evaluation (30 s)
**Follow-ups:** deals are ranked by expected revenue and contact urgency. Deals with conflicting or stale data sit
in a separate list instead of being ranked silently.
**Evaluation:** 100% conflict recall, 0% false conflicts, 0% debates on clean data, 100% valid citations, and
Arbiter beats a majority-plus-recency rule (68%) on identical evidence.

### Close (10 s)
> "Objective confidence decides when to argue, the losing argument is kept, and a person always decides."

---

**Q&A prep**
- *Did you invent agent debate?* No. The contribution is the gating (objective, non-LLM confidence), the preserved
  counterfactual, the deterministic discrepancy taxonomy, and human approval.
- *What if the judge is biased toward whichever option comes first?* On high-stakes conflicts it rules twice with the
  sides swapped; a flip escalates to a person.
- *What if the LLM hallucinates a citation?* The validator rejects any ID that isn't in the packet (with Claude the
  schema makes IDs an enum). Arbiter retries once, then uses a rule-based answer flagged for review.
- *Quota?* Clean data never calls an LLM, a standard conflict costs 3 calls, identical conflicts are cached, and a
  session cap turns further conflicts into provisional answers.
