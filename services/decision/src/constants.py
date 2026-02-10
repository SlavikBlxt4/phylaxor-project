# Decision Confidence Constants

# Confidence Baselines
# Conservative values to ensure safe hierarchy while allowing future scoring.
KB_BASE_CONFIDENCE = 60
AI_BASE_CONFIDENCE = 40

# History confidence is dynamic (calculated in history_score.py)
# but effectively gated > 85 to be eligible.
