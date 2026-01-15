import math
import statistics
import datetime
import os
import json

# Configuration Defaults
DEFAULT_CONFIG = {
    "MIN_SAMPLES": int(os.getenv("PHYLAXOR_HISTORY_MIN_SAMPLES", 3)),
    "THRESHOLD": float(os.getenv("PHYLAXOR_HISTORY_THRESHOLD", 85.0)),
    "HALF_LIFE_DAYS": float(os.getenv("PHYLAXOR_HISTORY_HALF_LIFE_DAYS", 14.0)),
    "MAX_AGE_DAYS": float(os.getenv("PHYLAXOR_HISTORY_MAX_AGE_DAYS", 30.0)),
    "CONSENSUS_RATIO": float(os.getenv("PHYLAXOR_HISTORY_CONSENSUS_RATIO", 0.6)),
    "LIMIT": int(os.getenv("PHYLAXOR_HISTORY_LIMIT", 20)),
    "VARIANCE_PENALTY": 0.25
}


def _get_rec_key(row):
    """
    Stable key for grouping recommendations.
    Prefers IDs (kb_id, rule_id) over summary if available.
    """
    rec = row.get("recommendation")
    if row.get("path") == "kb" and row.get("kb_id"):
        return f"kb:{row['kb_id']}"
    if row.get("rule_id") and row.get("rule_id") not in ("previous", "no_rule"):
         # 'previous' is typical for history items, not a stable grouping key itself usually unless trace
         return f"rule:{row['rule_id']}"
         
    if isinstance(rec, dict):
        return rec.get("summary", "")
    return str(rec)

def calculate_score(rows, config=None):
    """
    Evaluates history rows to determine eligibility and best recommendation.
    
    Args:
        rows: List of dicts/objects with keys:
              - path (str)
              - confidence (float/None)
              - created_at (datetime)
              - recommendation (dict/str)
              - id (any)
              - kb_id (optional)
              - rule_id (optional)
        config: Dict overriding defaults.
        
    Returns:
        (eligible (bool), best_recommendation (dict/None), reason (dict))
    """
    cfg = DEFAULT_CONFIG.copy()
    if config:
        cfg.update(config)

    now = datetime.datetime.now(datetime.timezone.utc)
    
    # 1. Filter valid rows
    valid_rows = []
    dropped_due_to_age = 0
    
    for r in rows:
        # Ignore fallback
        if r.get("path") == "fallback":
            continue
            
        # Ensure confidence is number
        conf = r.get("confidence")
        if conf is None:
            conf = 0.0
        else:
            conf = float(conf)
            
        # Check freshness
        created_at = r.get("created_at")
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=datetime.timezone.utc)
            
        age_delta = now - created_at
        age_days = age_delta.total_seconds() / 86400.0
        
        if age_days > cfg["MAX_AGE_DAYS"]:
            dropped_due_to_age += 1
            continue
            
        valid_rows.append({
            "original": r,
            "conf": conf,
            "age_days": max(0, age_days),
            "rec_key": _get_rec_key(r)
        })

    total_valid = len(valid_rows)
    
    reason = {
        "valid_count": total_valid,
        "total_input": len(rows),
        "dropped_due_to_age": dropped_due_to_age,
        "gating_reason": None,
        "score_avg": 0.0,
        "score_penalty": 0.0,
        "score_final": 0.0,
        "consensus_ratio": 0.0,
        "freshness_ok": True,
        "chosen_recommendation_key": None
    }

    # 2. Check strict freshness failure
    # If we had candidates but they were all dropped due to age, report specific reason
    if total_valid == 0 and len(rows) > 0 and dropped_due_to_age > 0:
         # Need to check if there were POTENTIALLY valid rows (non-fallback) that got dropped
         # Essentially, if valid_rows is 0 but we tried, and age killed them.
         reason["freshness_ok"] = False
         reason["gating_reason"] = "all_history_too_old"
         return False, None, reason

    # 3. Minimum Sample Check
    if total_valid < cfg["MIN_SAMPLES"]:
        reason["gating_reason"] = "insufficient_samples"
        return False, None, reason

    # 4. Consensus Check & Weighted Calcs
    groups = {}
    weighted_conf_sum = 0.0
    total_weight = 0.0
    
    # Store weights for variance calc
    weights = []
    confs = []
    
    for item in valid_rows:
        k = item["rec_key"]
        groups.setdefault(k, []).append(item)
        
        w = math.exp(-item["age_days"] / cfg["HALF_LIFE_DAYS"])
        item["weight"] = w
        
        weighted_conf_sum += item["conf"] * w
        total_weight += w
        
        weights.append(w)
        confs.append(item["conf"])

    # Calculate Consensus Ratio
    max_group_count = max(len(g) for g in groups.values()) if groups else 0
    consensus_ratio = max_group_count / total_valid if total_valid > 0 else 0
    reason["consensus_ratio"] = round(consensus_ratio, 2)
    
    if consensus_ratio < cfg["CONSENSUS_RATIO"]:
        reason["gating_reason"] = "low_consensus"
        return False, None, reason

    # 5. Scoring
    # Weighted Average
    score_avg = weighted_conf_sum / total_weight if total_weight > 0 else 0.0
    
    # Weighted Variance
    # sum(w * (x - mean)^2) / sum(w)
    # Using 'biased' weighted variance for MVP simplicity (like N vs N-1)
    if total_weight > 0 and len(confs) > 1:
        weighted_sq_diff_sum = sum(w * ((c - score_avg) ** 2) for w, c in zip(weights, confs))
        weighted_variance = weighted_sq_diff_sum / total_weight
        # stdev
        weighted_stdev = math.sqrt(weighted_variance)
    else:
        weighted_stdev = 0.0
        
    penalty = weighted_stdev * cfg["VARIANCE_PENALTY"]
    final_score = max(0.0, min(100.0, score_avg - penalty))
    
    reason["score_avg"] = round(score_avg, 2)
    reason["score_penalty"] = round(penalty, 2)
    reason["score_final"] = round(final_score, 2)
    
    if final_score < cfg["THRESHOLD"]:
        reason["gating_reason"] = "score_below_threshold"
        return False, None, reason
        
    # 6. Selection
    # Highest weighted support per group
    support_scores = {}
    for k, group_rows in groups.items():
        support = sum(item["weight"] for item in group_rows)
        support_scores[k] = support
    
    # Sort groups by support DESC
    sorted_candidates = sorted(groups.items(), key=lambda x: support_scores[x[0]], reverse=True)
    best_key = sorted_candidates[0][0]
    
    # Tie-breaking logic (most recent of the best group)
    best_support = support_scores[best_key]
    tied_keys = [k for k,v in support_scores.items() if abs(v - best_support) < 0.001]
    
    if len(tied_keys) > 1:
        best_rec_time = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
        for k in tied_keys:
            newest_in_group = max(groups[k], key=lambda x: x["original"]["created_at"])
            ts = newest_in_group["original"]["created_at"]
            if ts.tzinfo is None: ts = ts.replace(tzinfo=datetime.timezone.utc)
            if ts > best_rec_time:
                best_rec_time = ts
                best_key = k

    # Get most recent rec from winning group
    winner_group = groups[best_key]
    newest = max(winner_group, key=lambda x: x["original"]["created_at"])
    best_rec_obj = newest["original"]["recommendation"]

    reason["chosen_recommendation_key"] = best_key
    return True, best_rec_obj, reason
