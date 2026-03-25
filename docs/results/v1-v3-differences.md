# Behavioral Monitoring Roadmap: v1 vs v3 Differences

**v1:** `docs/plans/2026-03-12-sophiya-behavioral-monitoring-roadmap.md`
**v3:** `docs/plans/2026-03-24-sophiya-behavioral-monitoring-roadmap-v3.md`

---

| Aspect | v1 (Mar 12) | v3 (Mar 24) |
|--------|-------------|-------------|
| **Sessions** | Retroactive 20-min gap grouping from SpendLogs | Dropped entirely — fixed time windows (1h/24h/7d) |
| **Aggregator frequency** | Every 5 minutes | Once per day |
| **Stage 3 output** | 4 behavioral scores only | 4 scores + structured daily summary (topics, life events, quotes, operator note) |
| **Cross-day context** | None — each run is stateless | LLM receives a filtered "calendar" of previous notable days to connect patterns across days |
| **LLM backend** | Hardcoded Ollama | Configurable — Ollama, OpenRouter, OpenWebUI, anything via LiteLLM |
| **Profile purpose** | Read by middleware on every request (cached) | Read by soft middleware (direct DB query) + weekly report |
| **Intervention** | Full system: GREEN=pass, YELLOW=append nudge to response, RED=inject system prompt + operator alert + InterventionLog table | Simpler: fixed prompt templates injected into system message (YELLOW/RED), no InterventionLog |
| **Operator interface** | Real-time dashboard + webhook notifications | Weekly per-user report (SQL stats + notable days timeline), generated as file |
| **Tables** | 3 (Profile, History, Events) + future InterventionLog/InterventionRules | 4 (Profile, History, Events, DailySummary) |
| **Metrics** | Session-based (session duration, messages per session) + temporal | Temporal only — session metrics dropped |
| **Milestone 0** | Not present — jumps to code | Explicit design/spec milestone before any code |

---

## Key Conceptual Shifts

1. **From real-time monitoring to daily pattern analysis** — v1 tried to detect and intervene in near-real-time (5-min cycles). v3 accepts that behavioral patterns are daily phenomena and runs once per day.

2. **From numbers-only to narrative** — v1 produced only numeric scores. v3 adds structured daily summaries with life events, quotes, and cross-day operator notes — enabling an operator to read a user's story, not just their metrics.

3. **From complex intervention system to simple soft middleware** — v1 planned InterventionLog, InterventionRules, progressive escalation. v3 uses two fixed prompt templates (YELLOW/RED) and focuses the operator experience on the weekly report instead.
