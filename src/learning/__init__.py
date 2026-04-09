"""
Learning Loop module — PLANNED, NOT IMPLEMENTED.

Designed as a deterministic post-trade calibration layer that adjusts:
- execution threshold (rises if winrate < 35%, falls if > 55%)
- Decision Score sub-weights (correlation sub-score vs PnL, every 20 trades)
- position sizing multipliers (down with drawdown, up at equity ATH)
- cooldown duration (longer after consecutive losses)

Guardrails: threshold 55-80, weights 0.10-0.50, sizing 0.3-1.0x.

See ARCHITECTURE.md section 4 for the full design. The current pipeline
runs without this module — Decision Scorer weights are static.
"""
