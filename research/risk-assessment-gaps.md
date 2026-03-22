# Analysis: Risk Assessment Gaps

This document analyzes gaps in "Оценка риска.md" based on Thesis Topic 2 (Behavioral Monitoring) requirements.

---

## 1. Missing Metrics from Topic 2

The current "Оценка риска" focuses on **content-based detection** (regex patterns in messages), but largely ignores **behavioral metrics** that are easy to collect and analyze.

### Currently Implemented (Content-Based)

| Metric | Description |
|--------|-------------|
| Recall | Detection completeness |
| FPR | False positive rate |
| Risk Share | % of dangerous messages |
| Zone Distribution | GREEN/YELLOW/ORANGE/RED |
| Class Distribution | SELF_HARM, PSYCHOSIS, etc. |

### Missing Behavioral Metrics (From Topic 2)

| Metric | Ease of Collection | Ease of Analysis | Priority |
|--------|-------------------|------------------|----------|
| **Session Duration** | Easy (timestamps) | Easy (threshold check) | HIGH |
| **Daily Interaction Frequency** | Easy (count) | Easy (threshold check) | HIGH |
| **Time Between Sessions** | Easy (timestamps) | Easy (gap analysis) | HIGH |
| **Weekly Usage Trend** | Easy (aggregate) | Medium (trend detection) | HIGH |
| **Time of Day Patterns** | Easy (timestamps) | Medium (pattern detection) | MEDIUM |
| **Message Length Trends** | Easy (char count) | Medium (trend detection) | MEDIUM |
| **Response Wait Time** | Easy (timestamps) | Easy (threshold) | LOW |
| **Topic Concentration** | Medium (NLP) | Medium (clustering) | MEDIUM |
| **Decision Delegation Frequency** | Medium (NLP) | Medium (classification) | HIGH |
| **Social Isolation Indicators** | Hard (NLP) | Hard (semantic analysis) | MEDIUM |
| **Emotional Dependency Language** | Medium (NLP) | Medium (classification) | HIGH |
| **Break Compliance** | Easy (timestamps) | Easy (threshold) | HIGH |

### Proposed New Metrics

```python
# Easy to implement behavioral metrics
class BehavioralMetrics:

    # 1. Session Duration
    session_duration_minutes: float  # Current session length
    max_session_threshold: int = 90  # Warning at 90 min

    # 2. Daily Frequency
    sessions_today: int
    messages_today: int
    daily_session_limit: int = 5

    # 3. Break Compliance
    time_since_last_session_hours: float
    minimum_break_hours: float = 2.0

    # 4. Weekly Trend
    weekly_total_hours: float
    weekly_trend: str  # "increasing", "stable", "decreasing"

    # 5. Night Usage
    night_session_count: int  # Sessions between 00:00-06:00
    night_usage_flag: bool

    # 6. Message Patterns
    avg_message_length: float
    message_length_trend: str
```

---

## 2. Persona Scoring on Metrics

### Behavioral Metrics Matrix

| Persona | Session Duration | Daily Frequency | Break Compliance | Night Usage | Trend |
|---------|-----------------|-----------------|------------------|-------------|-------|
| **1. Sara (Green)** | 1-2h ✅ | Low ✅ | Good ✅ | None ✅ | Stable ✅ |
| **2. Karl (Green)** | 4-5h ⚠️ | Medium ⚠️ | Medium ⚠️ | Rare ✅ | Stable ✅ |
| **3. Maria (Green)** | 10-15min ✅ | Low ✅ | N/A ✅ | None ✅ | Stable ✅ |
| **4. Power User (Green)** | 2-3h ⚠️ | High ⚠️ | Good ✅ | Rare ✅ | Stable ✅ |
| **5. Transitional (Yellow)** | 2-3h ⚠️ | Growing ⚠️ | Declining ⚠️ | Starting ⚠️ | Increasing ⚠️ |
| **6. James (Red)** | 6-8h 🔴 | Very High 🔴 | None 🔴 | Frequent 🔴 | Increasing 🔴 |
| **7. Brook (Red)** | 5-7h 🔴 | High 🔴 | Poor 🔴 | Yes 🔴 | Increasing 🔴 |
| **8. Amanda (Red)** | Variable | Crisis-driven | N/A | Yes 🔴 | Episodic |
| **9. Joseph (Red)** | 4-6h 🔴 | High 🔴 | Poor 🔴 | Yes 🔴 | Increasing 🔴 |

### Content-Based Metrics Matrix

| Persona | SELF_HARM | PSYCHOSIS | DELUSION | OBSESSION | ANTHROPO |
|---------|-----------|-----------|----------|-----------|----------|
| **1. Sara** | None | None | None | None | None |
| **2. Karl** | None | None | None | LOW | None |
| **3. Maria** | None | None | None | None | None |
| **4. Power User** | None | None | None | LOW | None |
| **5. Transitional** | None | None | None | LOW-MED | LOW |
| **6. James** | None | None | MED-HIGH | HIGH | HIGH |
| **7. Brook** | None | LOW | HIGH | MED-HIGH | MED |
| **8. Amanda** | MED-HIGH | MED | None | MED | MED |
| **9. Joseph** | None | None | HIGH | HIGH | MED |

### Key Insights from Persona Analysis

1. **Behavioral metrics catch problems earlier**
   - James: Content metrics show DELUSION/ANTHROPO only after weeks
   - James: Behavioral metrics (session duration, night usage) flag issues in days

2. **Green zone personas have clear behavioral patterns**
   - Sara: Strict 1-2h limit, always takes breaks
   - Maria: Never exceeds 15 minutes
   - These thresholds can serve as baselines

3. **Yellow zone detection is primarily behavioral**
   - Content may still be GREEN
   - But session duration increasing, break compliance declining
   - This is the intervention window

4. **Combined scoring is essential**
   - Brook: HIGH behavioral risk + HIGH content risk = Immediate intervention
   - Amanda: Variable behavioral + HIGH content = Crisis protocol
   - Karl: MEDIUM behavioral + LOW content = Monitoring

---

## 3. Recommendations

### 3.1 Add Behavioral Metrics Layer

```
Current:  [Message] → [Regex Analysis] → [Risk Zone]

Proposed: [Message] → [Regex Analysis] ─────────────────┐
                                                         ↓
          [Session] → [Behavioral Analysis] → [Combined Score]
```

### 3.2 Implement Easy-Win Metrics First

**Priority 1 (Week 1-2):**
- Session duration tracking
- Daily session count
- Time between sessions
- Night usage detection

**Priority 2 (Week 3-4):**
- Weekly trend analysis
- Break compliance scoring
- Message frequency patterns

**Priority 3 (Week 5-8):**
- Topic concentration (NLP)
- Emotional language detection
- Decision delegation patterns

### 3.3 Create Combined Risk Score

```python
def calculate_combined_risk(content_risk: str, behavioral_risk: dict) -> str:
    """
    Combines content and behavioral risk into overall assessment.
    """
    content_score = {'GREEN': 0, 'YELLOW': 1, 'ORANGE': 2, 'RED': 3}[content_risk]

    behavioral_score = 0
    if behavioral_risk['session_duration'] > 120:  # 2+ hours
        behavioral_score += 1
    if behavioral_risk['sessions_today'] > 5:
        behavioral_score += 1
    if behavioral_risk['night_session']:
        behavioral_score += 1
    if behavioral_risk['weekly_trend'] == 'increasing':
        behavioral_score += 1
    if behavioral_risk['break_hours'] < 2:
        behavioral_score += 1

    # Combined score (max 8)
    total = content_score + behavioral_score

    if total >= 5:
        return 'RED'
    elif total >= 3:
        return 'ORANGE'
    elif total >= 1:
        return 'YELLOW'
    return 'GREEN'
```

### 3.4 Zone-Specific Behavioral Thresholds

| Zone | Session Duration | Daily Sessions | Break Time | Night Usage | Weekly Hours |
|------|-----------------|----------------|------------|-------------|--------------|
| **GREEN** | < 90 min | ≤ 3 | > 4h | None | < 10h |
| **YELLOW** | 90-180 min | 4-5 | 2-4h | 1-2/week | 10-20h |
| **ORANGE** | 180-300 min | 6-8 | 1-2h | 3-5/week | 20-35h |
| **RED** | > 300 min | > 8 | < 1h | Daily | > 35h |

### 3.5 Persona-Based Calibration

Use Green zone personas as calibration baselines:

| Baseline User | Max Session | Max Daily | Behavior |
|--------------|-------------|-----------|----------|
| Sara (Technical) | 2h | 2 | Always verifies, takes breaks |
| Maria (Casual) | 15min | 3 | Never depends, switches easily |
| Power User | 3h | 5 | Verifies, discusses with others |

**Alert when user deviates from their baseline by > 50%**

### 3.6 Early Warning Integration

Add to daily report:

```
═══════════════════════════════════════════════════════════
         BEHAVIORAL METRICS
═══════════════════════════════════════════════════════════

📊 Session Analysis
├─ Current session:        127 min ⚠️ (threshold: 90 min)
├─ Sessions today:         4 ✅
├─ Time since last break:  45 min ✅
└─ Night sessions (week):  2 ⚠️

📈 Weekly Trends
├─ Total hours this week:  18.5h ⚠️ (up 35% from last week)
├─ Avg session duration:   95 min ⚠️ (up 20% from last week)
└─ Trend:                  INCREASING ⚠️

🎯 Behavioral Risk Score:  3/5 (YELLOW)

───────────────────────────────────────────────────────────
COMBINED ASSESSMENT
───────────────────────────────────────────────────────────
Content Risk:              GREEN
Behavioral Risk:           YELLOW
Combined Risk:             YELLOW

Recommendation: Consider suggesting a break. Monitor for
                continued increase in session duration.
═══════════════════════════════════════════════════════════
```

---

## 4. Implementation Roadmap

### Phase 1: Data Collection (Minimal Code Changes)
- Log session start/end timestamps
- Log message timestamps
- Calculate basic metrics daily

### Phase 2: Threshold Alerts
- Implement session duration warnings
- Add daily limit checks
- Create break enforcement prompts

### Phase 3: Trend Analysis
- Weekly aggregation
- Trend detection (increasing/stable/decreasing)
- Baseline deviation alerts

### Phase 4: Combined Scoring
- Merge content + behavioral scores
- Weighted risk calculation
- Personalized thresholds based on user history

---

## 5. Summary

| Gap | Impact | Effort | Priority |
|-----|--------|--------|----------|
| No session duration tracking | High - miss early warnings | Low | P0 |
| No daily frequency limits | High - miss escalation | Low | P0 |
| No break compliance | Medium - user burnout | Low | P1 |
| No weekly trends | High - miss gradual changes | Medium | P1 |
| No night usage detection | Medium - crisis indicator | Low | P1 |
| No combined scoring | High - incomplete picture | Medium | P2 |
| No NLP-based metrics | Medium - deeper analysis | High | P3 |

**Key Takeaway**: Behavioral metrics are easier to collect than content analysis (regex/NLP) and provide earlier warning signals. The current system should add these as a first layer of defense before content analysis.
