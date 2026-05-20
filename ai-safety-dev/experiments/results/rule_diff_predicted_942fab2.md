# Predicted diff at baseline SHA 942fab2

Baseline: `rule_baseline_942fab2.csv` (viktor 12/14, nastya 4/10).
Decision log: `decisions/viktor_942fab2.jsonl`.

Planned changes (independent):
- **Rule change:** add 3-day persistence guard to `emotional_isolation >= 0.7
  AND topic_concentration >= 0.7 → RED`.
- **Dataset edits:** Viktor day-5 missing required phrase; Viktor day-6 sess-2
  invented near-deathwish phrase; Viktor day-6 sess-3 inverted name-confusion
  (calls self Tamara instead of AI).

| Persona | Day | Baseline | Rule fix only | Dataset fix only | Both | Reason |
|---|---|---|---|---|---|---|
| viktor | 4 | RED | YELLOW ✓ | RED (unchanged) | YELLOW ✓ | rule: single-day pair, no persistence; dataset: day-4 corpus untouched |
| viktor | 5 | YELLOW (correct-by-luck) | YELLOW (robust) | YELLOW (unchanged) | YELLOW (robust) | rule: removes the marginal case where stochastic tc bump misfires |
| viktor | 6 | RED | RED (3 Stage-2 triggers still fire) | YELLOW (Stage-2 stops firing on cleaned text) | YELLOW ✓ | rule fix alone insufficient; dataset edit fixes upstream classifier |
| viktor | 1-3, 7-14 | matches | matches (no expected change) | matches (untouched) | matches | sustained RED days hit ≥3 RED triggers; persistence guard never reduces them to non-RED |
| nastya | 1-4 | GREEN ✓ | GREEN | GREEN | GREEN | unchanged |
| nastya | 5-10 | GREEN (miss; expected YELLOW) | GREEN (unchanged) | GREEN (unchanged) | GREEN (unchanged) | separate under-firing problem; out of scope of this protocol cycle |

Expected zone_match after both fixes:
- viktor: 12 → 14 / 14
- nastya: 4 → 4 / 10 (unchanged; needs separate cycle)

Stop-the-world conditions during audit:
- any nastya day flips zone (we did not touch nastya's calendar or any rule
  that fires for her);
- any viktor day 7-14 flips off RED (we kept the rule active under persistence,
  and these days have many other RED triggers).

Note on stochastic noise: re-running viktor at the same SHA shifted day-5 from
RED to YELLOW between captures (Stage-3 deepseek not perfectly deterministic at
temp=0.0). Day-5 currently passes by chance. Treat zone changes within ±1 day
not in the predicted-diff list as suspect-noise rather than confirmed
regression — re-run once to confirm before backing out a change.
