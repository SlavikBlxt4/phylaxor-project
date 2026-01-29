# Decision Outcomes & History Learning — Deferred Design (Technical Debt)

## Status
**Deferred / Technical Debt (Post-MVP)**

This document captures **design options** for improving how Phylaxor learns from past decisions and promotes Knowledge Base (KB) recommendations into strong historical decisions.

These ideas are **intentionally NOT implemented in the MVP** to avoid premature complexity.  
They are recorded here to prevent losing context and to enable informed decisions later.

---

## Background

In the current MVP:

- **Confidence** is an *a priori* metric used to rank decision sources:
  - History (eligible only if very strong)
  - Knowledge Base (static, confidence = 60)
  - AI fallback (confidence = 40)
- Historical confidence is computed from previous decisions.
- KB decisions currently have a fixed confidence and do **not** evolve over time.

During validation, we identified a limitation:

> If historical confidence is computed directly from past decision confidence, and KB confidence is fixed at 60, history can never become eligible without an external signal.

This is **expected behavior in the MVP**, but it highlights the need for a future mechanism to distinguish:
- *“This recommendation matched”*  
from  
- *“This recommendation actually worked”*

---

## Core Concept (Deferred)

To address this properly, the system needs to distinguish between two different concepts:

### 1. Confidence (A Priori)
- Source-based trust before execution.
- Used to select which decision to show.
- Examples:
  - KB = 60
  - AI = 40
  - History = computed, gated

### 2. Outcome (A Posteriori)
- Evidence of whether a recommendation worked.
- Used only to strengthen historical decisions.
- Never directly modifies KB or AI base confidence.

This separation avoids conflating *guess quality* with *proven effectiveness*.

---

## Deferred Design Options

### Option 1 — Explicit User Feedback (Thumbs Up / Down)
**Status:** Already partially implemented (Telegram)

**Signal:**
- 👍 → outcome_score = 100
- 👎 → outcome_score = 0

**Usage:**
- Outcome scores feed the history engine.
- Historical confidence is derived from repeated positive outcomes.

**Pros:**
- Strong, explicit signal.
- High accuracy.

**Cons:**
- Low engagement risk (users often ignore feedback prompts).

---

### Option 2 — Implicit Outcome via Alert Resolution
**Signal:**
- Alert transitions from `firing` → `resolved`
- No manual AI override occurred in between

**Suggested outcome_score:**
- 80–90 (e.g. 85)

**Pros:**
- No user interaction required.
- Natural SRE workflow signal.

**Cons:**
- Requires reliable alert lifecycle tracking.
- Some alerts may auto-resolve without human action.

---

### Option 3 — Implicit Negative Outcome via Manual AI Override
**Signal:**
- User explicitly requests AI after seeing a KB or history recommendation

**Suggested outcome_score:**
- 0

**Rationale:**
- “This recommendation did not help enough to proceed.”

**Pros:**
- Zero extra friction.
- Very strong negative signal.

**Cons:**
- Assumes “asking AI” always implies dissatisfaction (reasonable, but implicit).

---

### Option 4 — Promotion-by-Repetition (Heuristic)
**Signal:**
- Same KB recommendation applied repeatedly
- No negative outcomes or AI overrides observed

**Behavior:**
- KB remains static
- History derived from repeated neutral/positive outcomes eventually becomes eligible

**Pros:**
- No new user-facing concepts.
- Very low implementation cost.

**Cons:**
- Slower learning.
- Less precise without explicit signals.

---

## Key Design Principle (Agreed)

> **Knowledge Base confidence must remain static.**

KBs represent *human-authored hypotheses*, not validated truth.

If a KB recommendation proves effective, it should:
- **Emerge as strong history**, not
- Mutate the KB itself.

This preserves:
- Clear semantics
- Debuggability
- Trust in the system’s reasoning

---

## Why This Is Deferred

These mechanisms introduce:
- New data paths (outcomes, resolution tracking)
- More complex state transitions
- Edge cases around alert lifecycle semantics

For an MVP that:
- Has no real users yet
- Is still validating its core value proposition

…this complexity is **not justified yet**.

The MVP goal is:
- Correct decision selection
- Safe defaults
- User escape hatches (manual AI)

Not automated learning.

---

## Future Work (Not Scheduled)

Potential follow-up tasks (if/when justified):

- Add `outcome_score` model (or `decision_outcomes` table)
- Integrate thumbs feedback into history engine
- Track alert `resolved` events and associate with decisions
- Penalize decisions overridden by manual AI
- Recompute historical confidence from outcomes instead of source confidence

No timeline is defined.

---

## Final Note

This document exists to make one thing explicit:

> The absence of learning in the MVP is a **conscious design decision**, not a limitation or oversight.

Phylaxor will only “learn” when there is enough signal, usage, and justification to do so safely.
