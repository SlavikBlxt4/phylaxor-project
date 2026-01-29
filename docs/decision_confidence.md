# Decision Confidence System

## 1. Concept of Confidence

**Confidence** in Phylaxor is an **internal numeric metric (0-100)** used exclusively to order and select the best available decision for a given alert.

### What it IS:
- A relative ranking score.
- A deterministic value derived from source reliability (KB vs AI) or statistical strength (History).
- The sole arbiter for which recommendation is shown to the user.

### What it is NOT:
- A probability of success (e.g., 60% confidence does not mean 60% change of fixing the issue).
- An absolute truth claim.
- Visible to the end-user (usually), unless debugging.

**Why it exists**: To decouple the *source* of a decision from its *priority*. Instead of hardcoded `if history > kb > ai` logic, we assign scores and simply pick `max(score)`. This allows future flexibility (e.g., a very weak history match could theoretically be outranked by a verified KB match).

**TL;DR**: Confidence is a sorting key, not a promise.

---

## 2. Decision Selection Model

Phylaxor evaluates multiple decision candidates in parallel and selects the winner based on the highest confidence score.

### Selection Flow

1.  **AI Fallback (Manual)**: If explicitly triggered by the user (`force_ai=true`), this bypasses all others.
2.  **Candidates Collection**:
    *   **History**: Calculated dynamically based on past success. Only candidates with score > 85 are eligible.
    *   **Knowledge Base (KB)**: Added if the alert matches a defined KB rule.
    *   **AI Fallback (Auto)**: Always available as a low-confidence baseline.
3.  **Selection**: The candidate with the highest integer confidence is chosen.
4.  **Tie-breaking**: In the rare event of a tie, priority is: History > KB > AI.

### Pseudocode

```python
candidates = []

# 1. History
hist_rec, hist_score = history_engine.lookup(alert)
if hist_rec and hist_score > 85:
    candidates.append({
        "source": "history",
        "rec": hist_rec,
        "confidence": hist_score
    })

# 2. Knowledge Base
kb_match = kb_engine.match(alert)
if kb_match:
    candidates.append({
        "source": "kb",
        "rec": kb_match,
        "confidence": 60
    })

# 3. AI Fallback (Auto)
candidates.append({
    "source": "ai",
    "rec": generate_generic_advice(),
    "confidence": 40
})

# Select Winner
best_decision = max(candidates, key=lambda x: x["confidence"])
```

---

## 3. Confidence Values by Decision Path (MVP)

We use conservative base values to enforce a safe hierarchy while allowing future tuning.

| Source | Base Confidence | Rationale |
| :--- | :--- | :--- |
| **History** | **Variable (85-100)** | Real-world evidence is king. If it worked before, it is ranked highest. |
| **KB** | **60** | KBs are static rules written by humans. They are "good matches" but lack the runtime proof of history. |
| **AI** | **40** | Generative/heuristic fallback. Useful but lowest trust. |

**Why these values?**
*   **Gap between 60 and 85**: Ensures a freshly matched KB item never overrides a proven historical fix (which starts at >85).
*   **Gap between 40 and 60**: Ensures AI guesses never override a concrete KB rule.

---

## 4. Historical Confidence Formula

The historical score measures the **repeatability and consensus** of past decisions.

1.  **Recency Weighting**: Older decisions count for less. Uses exponential decay (half-life of 14 days).
    *   *Why*: Infrastructure changes. A fix from 6 months ago is less likely to be relevant today.
2.  **Minimum Sample Threshold**: Requires at least 3 occurrences.
    *   *Why*: Prevents "one-hit wonders" or flukes from establishing a pattern.
3.  **Maximum Age Filtering**: Drops decisions older than 30 days.
    *   *Why*: Hard cutoff to ensure relevance.
4.  **Consensus Ratio**: Requires >60% agreement on the resolution.
    *   *Why*: If an alert was fixed 5 different ways, we don't know which one works. We need a clear winner.
5.  **Variance Penalty**: Penalizes scores if confidence fluctuated wildly in the past.
    *   *Why*: Consistent performance > sporadic spikes.
6.  **Final Threshold**: If the final score is < 85, the history is deemed "ineligible".
    *   *Why*: Quality gate. We prefer falling back to KB/AI over recommending "maybe".

---

## 5. KB Confidence Formula

### MVP (Current State)
*   **Formula**: `Confidence = 60` (Constant)
*   **Matchers**: `alertname` only (exact match)
*   **Rationale**:
    *   We currently only match on `alertname`.
    *   An `alertname` match implies the KB is *relevant*, but because we ignore labels/context in matching, we cannot be 100% sure it's the *exact* root cause.
    *   60 represents "likely relevant but unverified context".

### Future Evolution (Design Only)
When optional matchers (labels, logs keys) are added:
`ratio = (sum(weight_i * match_i)) / (sum(weight_i))`
`confidence = KB_BASE + KB_BONUS_MAX * ratio`

*   **Required Matchers**: Must match or confidence is 0.
*   **Optional Matchers**: Act as multipliers/adders.
*   **Why**: A KB matching `alertname` AND `namespace=production` AND `error_code=500` is significantly more trustworthy than just `alertname` match.

---

## 6. Manual AI Escape Hatch

Users can force an AI analysis even if a KB or History match exists.

*   **Mechanism**: User triggers action (UI button / CLI flag) -> Request payload includes `force_ai=true`.
*   **Behavior**:
    *   Bypasses History/KB lookup.
    *   Calls AI Service immediately.
    *   stores decision with `triggered_by="manual"`.
    *   **Does NOT overwrite**: The original KB/History decision remains in history; this creates a *new*, separate decision record.
*   **Criticality**:
    *   **Agency**: Operators know more than the system. If the KB is wrong, they need a way to ask "what else?"
    *   **Coverage**: KBs are rarely complete. AI fills the gaps on demand.

---

## 7. Explicit Non-Goals (MVP)

The following features are distinctly **out of scope** for this phase:

*   **User-editable KBs**: KBs are code/config artifacts, not wiki pages.
*   **Advanced KB Weighting**: No complex "weighted sum" logic for matchers yet.
*   **Automatic KB Learning**: The system does NOT auto-promote history to KB.
*   **AI Self-Assessment**: We blindly trust the AI's base confidence (40); we do not ask the LLM "how confident are you?".
*   **UI for KB Management**: GitOps only.
