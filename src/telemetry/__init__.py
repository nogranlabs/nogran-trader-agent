"""
Telemetry module — PLANNED, NOT IMPLEMENTED.

Designed to host:
- TradeJournal: structured per-trade snapshots beyond the JSONL audit log
- PerformanceReport: weekly aggregations (Sharpe, max DD, profit factor,
  expectancy, hit rate by setup)
- Metric exporters: Prometheus / OpenTelemetry endpoints for live monitoring

The current pipeline writes audit data to logs/decisions/*.jsonl via
src/compliance/decision_logger.py. The dashboard (dashboard/app.py) reads
those JSONL files directly. Telemetry is the next iteration when there's
more than one consumer of the same metrics.
"""
