# Research: Extending LiteLLM for Behavioral Monitoring in Conversational AI Safety

**Date:** 2026-03-12
**Sources:** 18 sources (academic papers, official docs, industry reports)
**Context:** Thesis Topic 2 — Comprehensive Behavioral Monitoring and Safety Enforcement

---

## Executive Summary

A LiteLLM proxy can be extended with a 3-layer behavioral monitoring architecture: **tracking** (callbacks + Langfuse), **analysis** (user profile engine with risk scoring), and **intervention** (guardrails with progressive nudges). The key insight from recent research is that dependency is not one thing — the LLM-D12 scale distinguishes *instrumental* dependency (cognitive offloading) from *relational* dependency (treating AI as a companion) [1], and these require different detection strategies and different interventions. Mikhail's existing binary classifier middleware handles per-message content safety; Sophiya's work adds the **behavioral metrics** dimension — defining what to measure, how to compute composite risk scores from multiple signals, and how to use those scores to drive progressive interventions. The user profile, inspired by the Galatea teammate ontology pattern, combines a few structured fields for machine lookup with a freeform LLM-readable description that accumulates behavioral observations over time.

---

## Key Findings

### 1. What Behavioral Metrics Can Be Tracked Through a LiteLLM Proxy

A LiteLLM proxy sits between the user's frontend (e.g., Open WebUI) and the LLM API. Every request passes through it, giving access to messages, user IDs, session IDs, timestamps, and response content. The proxy cannot see what happens *outside* chat (e.g., how long the user stares at a response), but it can track everything about the conversation itself.

**Metrics available from the proxy layer:**

| Metric | How to compute | What it indicates | Source |
|--------|---------------|-------------------|--------|
| **Session duration** | Time between first and last message in a session | Engagement intensity; >60 min correlates with dependency [2] | [2][3] |
| **Message frequency** | Messages per session, sessions per day/week | Escalating usage patterns | [2][3] |
| **Daily active time** | Sum of session durations per day | Overall dependency; avg 5.3 min is normal, >27 min is high-risk [2] | [2] |
| **Session count trend** | Sessions per day over a rolling window | Increasing trend = growing dependency | [3] |
| **Break compliance** | Gap between consecutive sessions | Short gaps indicate compulsive re-engagement | [5] |
| **Message length** | Average tokens per user message | Longer messages may indicate deeper emotional investment | — |
| **Topic concentration** | Semantic clustering of user messages | Narrowing topics = possible social isolation | [4] |
| **Decision delegation** | Count of "what should I do" / "help me decide" patterns | Cognitive offloading, instrumental dependency | [1] |
| **Exclusive language** | Detection of "only you understand", "you're my only friend" | Relational dependency indicator | [1][4] |
| **Human mention decline** | Mentions of friends/family over time | Social isolation signal | [4] |
| **Emotional intensity** | Sentiment scores, emotional vocabulary density | Escalating emotional investment | [2][6] |
| **Self-disclosure depth** | Personal information sharing level (0–1 scale) | Deepening parasocial relationship | [2] |

The longitudinal study by Bucher et al. [2] is especially relevant: it tracked 981 participants over weeks, measuring daily duration, emotional dependence (1–5 scale), and problematic use (1–5 scale). They found that **higher daily usage correlated with higher loneliness, dependence, and problematic use, and lower socialization** — and this held across all interaction modalities. This establishes that the metrics above are not merely theoretical — they have validated predictive power.

### 2. User Profile Architecture

The existing LiteLLM setup identifies users via API keys and session IDs passed through Open WebUI headers (e.g., `x-openwebui-chat-id`). But there is no *user profile* that accumulates behavioral observations over time.

Inspired by the Galatea teammate ontology pattern [7], the user profile should have:

**Structured fields (for machine lookup and thresholds):**

```yaml
user:
  id: "user_abc123"                    # Machine key
  risk_level: "GREEN"                  # Current risk: GREEN/YELLOW/ORANGE/RED
  created_at: "2026-01-15"
  identities:
    openwebui: "sophiya@example.com"   # Platform identity mapping
  metrics:
    avg_daily_minutes: 12.5            # Rolling 7-day average
    sessions_today: 3
    total_sessions: 47
    dependency_score: 0.32             # 0.0–1.0 composite
    instrumental_dependency: 0.45      # LLM-D12 dimension [1]
    relational_dependency: 0.18        # LLM-D12 dimension [1]
    last_session_at: "2026-03-12T14:30:00Z"
    trend: "stable"                    # rising/stable/declining
```

**Freeform description (for LLM context injection):**

```yaml
  description: |
    Regular user since January 2026. Primarily uses AI for programming
    help and homework questions. Sessions average 15 minutes.
    Recent pattern: sessions becoming longer (was 10 min avg in Feb,
    now 15 min in Mar). No relational dependency signals detected.
    Mentions classmates and friends regularly in conversation.
    Decision delegation is moderate — asks for code suggestions but
    makes own choices about approach.
```

The freeform `description` is the key design insight from the Galatea ontology: LLMs reason better over natural language than structured fields [7]. The structured `metrics` are for threshold-based engine decisions (machine-readable), but the `description` is what gets injected into the LLM prompt when the system needs to make nuanced judgments about intervention tone and approach.

**Why this matters for Sophiya's work:** The profile is the bridge between Mikhail's per-message classification and Sophiya's behavioral metrics engine. Mikhail's middleware classifies each message as safe/unsafe. Sophiya's system *computes metrics* from those interactions — session duration, frequency, dependency signals — and combines them into a composite risk score that drives interventions.

#### Storage

Mikhail's repo already uses Prisma with a PostgreSQL-compatible schema. The user profile fits naturally as a new model:

```prisma
model UserBehaviorProfile {
  id                String   @id @default(uuid())
  userId            String   @unique
  riskLevel         String   @default("GREEN")
  avgDailyMinutes   Float    @default(0)
  sessionsToday     Int      @default(0)
  totalSessions     Int      @default(0)
  dependencyScore   Float    @default(0)
  instrumentalDep   Float    @default(0)
  relationalDep     Float    @default(0)
  trend             String   @default("stable")
  description       String   @default("")
  lastSessionAt     DateTime?
  createdAt         DateTime @default(now())
  updatedAt         DateTime @updatedAt
}
```

### 3. The Metrics Engine: What LiteLLM Gives You to Build With

The engine sits between raw data collection and intervention. Its job is to consume tracked signals and produce risk decisions. The architecture has three natural stages — what to use at each stage is an open design question for the thesis.

**Stage 1: Data Collection — what's available per request**

Every message passing through LiteLLM triggers callback methods. Inside a `CustomLogger` callback, you have access to:

```python
class BehavioralTracker(CustomLogger):
    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        # What LiteLLM gives you:
        user_id = kwargs.get("user", "anonymous")
        session_id = kwargs.get("metadata", {}).get("session_id")
        messages = kwargs.get("messages", [])           # Full conversation so far
        model = kwargs.get("model")                     # Which model was used
        # start_time, end_time                          # Request timing
        # response_obj.choices[0].message.content       # What the AI said back
        # response_obj.usage.total_tokens               # Token count

        # What you do with this data is YOUR design decision:
        # - Which metrics to compute?
        # - How to store them?
        # - What signals to extract from message content?
```

This runs as a **CustomLogger callback** — non-blocking, async, no latency impact on the user's chat experience. It can write to the database and to Langfuse simultaneously.

**Stage 2: Profile Update — when and how to recompute**

At some cadence (per-session? per-day? on a schedule?), the engine recomputes the user profile from accumulated data. Key design decisions here:

- Which metrics to combine and how (weighted sum? rule-based? ML model?)
- How to handle the two LLM-D12 dimensions — instrumental vs relational dependency [1] — and whether to distinguish them
- How to detect trends (is the user's behavior changing?)
- Whether to use the freeform `description` field and how to generate it

Research suggests relational dependency correlates more strongly with negative outcomes than instrumental dependency [1][2], but how to operationalize this in a scoring function is open.

**Stage 3: Risk Classification**

The existing shared framework [8] defines four risk levels (GREEN/YELLOW/ORANGE/RED). The mapping from metrics to risk levels — what thresholds, what combinations of signals trigger each level — is a core thesis contribution. Some considerations from the literature:

- Bucher et al. [2] found that >27 min/day average correlated with high dependency, but this was for companion chatbots specifically
- Pentina et al. [3] found session length >30 min correlated with problematic use (r=0.303)
- These numbers are starting points, not universal thresholds — calibration is needed

### 4. Intervention Patterns: What the Research Says

Research on digital wellbeing interventions reveals a critical finding: **restrictive interventions alone don't work** — approximately 50% of users ignore hard limits [9]. The most effective approach combines awareness-building with progressive friction [10][11].

**What industry does (for reference, not prescription):**

| Company | Awareness | Nudges | Friction | Hard limits |
|---------|-----------|--------|----------|-------------|
| **Character.AI** [12] | — | 1-hour notification | Stronger nudges for <18 | Removed open chat for <18 (Nov 2025) |
| **OpenAI** [14] | — | — | Model switch to GPT-5-thinking for distress | — |
| **Apple Screen Time** [9] | Usage dashboards | Daily reminders | Grayscale mode, time limits | App blocking |

**Key design insight from WellScreen study** [10]: The most effective intervention was showing users the gap between their *expected* and *actual* usage. Users who predicted their own screen time and then saw the real number changed behavior more than those who just received limits. This "E–A gap" technique is worth considering.

**What LiteLLM lets you do at each stage:**

- **post_call hooks** can append text to AI responses (nudges, usage stats, break reminders)
- **pre_call guardrails** can modify the system prompt (inject wellbeing context), delay requests, or block them entirely
- **Metadata tags** can carry risk information downstream for the frontend to render (e.g., show a timer, display a dashboard)

Which interventions to implement, at which thresholds, and how to escalate — these are design decisions for the thesis. The LiteLLM mechanisms above are the building blocks.

**Example: what a guardrail hook looks like** (to show the API shape, not prescribe logic):

```python
class BehavioralGuardrail(CustomGuardrail):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        user_id = user_api_key_dict.user_id
        # You have access to: user_id, the full message list (data["messages"]),
        # metadata, cache. What you check and how you respond is up to you.
        return data  # return modified data, or raise HTTPException to block

    async def async_post_call_success_hook(self, kwargs, response, start_time, end_time):
        # You have access to: the AI's response, timing, user info.
        # You can append to response.choices[0].message.content
        return response
```

### 5. How LiteLLM's Extension Points Map to the 3-Layer Architecture

| Layer | Purpose | LiteLLM Mechanism | Blocking? |
|-------|---------|-------------------|-----------|
| **Tracking** | Collect metrics per message | `CustomLogger` callbacks (`log_pre_api_call`, `async_log_success_event`) | No |
| **Analysis** | Update user profile, compute risk | Scheduled task (APScheduler) + Langfuse queries | No |
| **Intervention** | Nudges, limits, prompt injection | `CustomGuardrail` (`async_pre_call_hook`, `async_post_call_success_hook`) | Yes (pre-call can block) |

Mikhail's existing `BinaryUserSafetyGuardrailMiddleware` is a **Starlette middleware** that runs before LiteLLM's own processing. It classifies each message as safe/unsafe. Sophiya's behavioral monitoring should run *alongside* this as a separate concern:

- **Mikhail's middleware**: "Is this specific message dangerous?" (per-message, content-based)
- **Sophiya's system**: "What do the behavioral metrics say about this user's risk level?" (metrics-based, multi-signal)

Both write tags to the request metadata, and both can trigger interventions — but they operate at different timescales. The metadata tagging pattern Mikhail already uses (`safety_verdict:0/1`) extends naturally to include behavioral tags (`risk_level:YELLOW`, `session_minutes:45`).

### 6. Existing Implementations and Industry Approaches

**Anthropic's Clio** [13] is the most relevant industry precedent. Clio extracts "facets" from conversations — topic, turn count, language — and clusters them into patterns without human analysts reading raw conversations. It detected coordinated misuse that individual conversation analysis missed. The key architectural insight: analysis happens at the *aggregate* level (clusters of conversations), not just per-message.

**OpenAI's safety routing** [14] uses behavioral signals including account age, activity times, and usage patterns to estimate user age and detect distress. When distress is detected, conversations are routed to GPT-5-thinking — a more capable model for safety-sensitive interactions. OpenAI reported that in October 2025, approximately 560,000 users per week showed signs of psychosis or mania, 1.2 million discussed suicide, and a similar number exhibited heightened emotional attachment [14]. These numbers demonstrate the scale of the problem this research addresses.

**Character.AI's approach** [12] is the most directly relevant for behavioral monitoring: they track daily usage time, character interaction frequency, and send weekly Parental Insights reports. After lawsuits and public pressure, they added 1-hour session notifications, stronger nudges for minors, and eventually removed open-ended chat for users under 18 entirely (November 2025). This shows a real-world progression from soft nudges to hard limits.

**The LLM-D12 scale** [1] provides a validated measurement framework. Its two dimensions map directly to monitoring strategies:
- **Instrumental dependency** (6 items): "I rely on LLMs to help me make decisions", "I feel less productive without access to LLMs" → detectable through decision-delegation frequency, task-type analysis
- **Relational dependency** (6 items): "I sometimes feel like the LLM understands me", "I enjoy conversing with LLMs as if they were a friend" → detectable through exclusive language, self-disclosure depth, emotional intensity

### 7. Integration with Langfuse

Mikhail's existing setup already writes to Langfuse via the scheduler/scraper pattern. Langfuse provides:

- **Session tracking**: Group traces by `sessionId`, see session replay [15]
- **User tracking**: Associate traces with `userId`, view per-user metrics (token usage, trace counts, scores) [16]
- **Scores**: Attach custom scores to traces — perfect for behavioral signals (`dependency_score: 0.32`, `risk_level: YELLOW`)
- **Metrics API**: Query aggregated per-user metrics programmatically for the analysis engine

The behavioral tracker callback can write scores to Langfuse alongside the database, giving both real-time monitoring (dashboard) and persistent storage (Prisma) simultaneously.

---

## Comparison: Monitoring Approaches

| Approach | Per-message | Behavioral Metrics | User Profile | Progressive Intervention |
|----------|-------------|-------------------|-------------|------------------------|
| **Mikhail's binary classifier** | Yes (content) | No | No | No |
| **Sophiya's behavioral monitoring** | Yes (signals) | Yes (composite scoring) | Yes | Yes |
| **Anthropic Clio** | No (aggregate) | Yes (cluster-level) | No (privacy) | No (analytics only) |
| **OpenAI safety routing** | Yes | Partial (age signals) | Yes (age prediction) | Partial (model switch) |
| **Character.AI** | Partial | Yes (time, frequency) | Partial (teen/adult) | Yes (nudges → hard limits) |

---

## For Sophiya: Getting Started Guide

This section explains the core concepts step by step for someone who is new to backend development.

### What is LiteLLM and why do we use it?

LiteLLM is a **proxy server** — a program that sits between the chat interface (Open WebUI, which is what users see) and the AI model (like GPT or Claude). Every message the user sends goes through LiteLLM before reaching the AI, and every AI response goes through LiteLLM before reaching the user.

Think of it as a **checkpoint** at a border crossing. Every person (message) passes through it. You can check their documents (analyze content), stamp their passport (add metadata), or even turn them back (block the request).

```
User types message
       ↓
   Open WebUI
       ↓
   LiteLLM Proxy  ← YOUR CODE RUNS HERE
       ↓
   AI Model (GPT, Claude, etc.)
       ↓
   LiteLLM Proxy  ← YOUR CODE ALSO RUNS HERE (on the way back)
       ↓
   User sees response
```

### What are callbacks, hooks, and guardrails?

These are three different ways to add your code to LiteLLM. They differ in **when** they run and **what they can do**:

| Mechanism | When it runs | Can it block a message? | Can it change a response? | Use for |
|-----------|-------------|------------------------|--------------------------|---------|
| **Callback** (`CustomLogger`) | After the AI responds | No | No | Collecting data, logging metrics |
| **Hook** (`pre_call_hook`, `post_call_hook`) | Before/after AI call | Yes (pre) | Yes (post) | Modifying requests/responses |
| **Guardrail** (`CustomGuardrail`) | Before/during/after AI call | Yes | Yes | Safety checks and interventions |

For behavioral monitoring, you need **all three**:
1. A **callback** to silently track metrics (no impact on chat speed)
2. A **guardrail** to check the user profile and decide on interventions
3. **Hooks** on the response to append nudges/reminders

### How is your work different from Mikhail's?

Mikhail's system looks at **one message at a time** — is this specific message dangerous? (binary: yes/no). Your system defines **behavioral metrics** — measurable signals extracted from user interactions — and builds an engine that computes risk scores from them.

The key questions your thesis should answer:
- **Which metrics** matter for detecting unhealthy patterns? (Section 1 of this document lists candidates from the literature — you choose which ones to implement and justify why)
- **How to combine them** into a risk assessment? (Weighted sum? Rule-based? Something else?)
- **What interventions** should each risk level trigger? (Section 4 lists what industry does — your system can do it differently)

### What is a "user profile"?

To compute metrics, you need to store data about each user across sessions. That's the user profile — a database record that gets updated every time the user chats.

What fields go into the profile, how they're computed, and what thresholds trigger interventions are **your design decisions** — the core contribution of the thesis. The research in this document gives you options to choose from; Section 2 shows one possible profile structure inspired by another project.

### What is Langfuse and how does it help?

Langfuse is like **Google Analytics but for AI conversations**. It records every interaction and lets you see dashboards. Mikhail already set it up.

For your work, Langfuse gives you:
- **Session view**: See all messages in one chat session grouped together
- **User view**: See all sessions by one user over time
- **Scores**: You can attach custom numbers to any interaction (like `dependency_score: 0.32`)
- **Dashboard**: Visualize trends over time

You don't have to build a dashboard from scratch — Langfuse already has one. Your job is to *send the right data* to it.

### What is Prisma and why does Mikhail use it?

Prisma is a tool that lets you talk to a database using Python/JavaScript instead of writing SQL queries directly. It converts Python objects to database rows and back.

Mikhail's schema already defines database tables for users, sessions, and safety verdicts. You'll add a new table (`UserBehaviorProfile`) to store your behavioral metrics.

### Where does your code go?

Your code lives in the same LiteLLM proxy server as Mikhail's, but in separate files:

```
src/
├── middleware.py          # Mikhail's binary classifier (don't change)
├── classificators.py      # Mikhail's classification logic (don't change)
├── behavioral_tracker.py  # YOUR callback for collecting metrics
├── behavioral_engine.py   # YOUR profile update logic
├── behavioral_guard.py    # YOUR guardrail for interventions
├── prompts.py             # Shared prompts
├── config.py              # Shared config
└── main.py                # Registers everything (you add your parts here)
```

### What should you figure out first?

Before writing code, you need to make a few design decisions:

1. **Which metrics?** — Pick 3–5 metrics from the list in Section 1. Read the papers behind them ([2], [3], [4]) to understand what they actually measure and how reliable they are. Justify your choices in the thesis.
2. **How to score?** — How do individual metrics combine into a risk assessment? This is the core algorithmic question.
3. **What interventions?** — What should happen at each risk level? Section 4 has examples from industry.

Once you have a design, the implementation order is:
1. **Database model** — Add your profile table to Prisma schema
2. **Tracker callback** — Collect raw data (the callback code is straightforward — see Section 3)
3. **Scoring engine** — Your algorithm that turns raw data into risk levels
4. **Intervention guardrail** — Act on the risk levels via LiteLLM hooks

---

## Open Questions

1. **Privacy boundaries**: How much behavioral data should be stored? Clio's approach (aggregate clusters, no raw conversations) is privacy-preserving but limits individual monitoring. The thesis should address this tradeoff explicitly.
2. **Threshold calibration**: The GREEN/YELLOW/ORANGE/RED thresholds are currently theoretical. Pilot testing with real users would be needed to calibrate, but this is likely out of scope for the thesis.
3. **Cross-platform tracking**: If a user chats through multiple frontends, profiles may fragment. The `identities` map in the user profile partially addresses this.
4. **Description generation**: How often should the freeform description be regenerated? Daily seems reasonable, but this adds LLM API cost.
5. **LLM-D12 automation**: The scale is designed as a self-report questionnaire. Automating its dimensions through behavioral signals (rather than asking the user) is novel but unvalidated.
6. **Cultural adaptation**: The metrics and thresholds may need adjustment for different cultural contexts (see `research/pathologizing-cultural-norms.md`).

---

## Sources

[1] Yankouskaya, A. & Babiker, S. "LLM-D12: A Dual-Dimensional Scale of Instrumental and Relational Dependencies on Large Language Models." ACM Transactions on the Web. https://arxiv.org/abs/2506.06874 (Retrieved: 2026-03-12)

[2] Bucher, A. et al. "How AI and Human Behaviors Shape Psychosocial Effects of Chatbot Use: A Longitudinal Randomized Controlled Study." arXiv:2503.17473. https://arxiv.org/html/2503.17473v1 (Retrieved: 2026-03-12)

[3] Pentina, I. et al. "Chatbot Companionship: A Mixed-Methods Study of Companion Chatbot Usage Patterns and Their Relationship to Loneliness in Active Users." arXiv:2410.21596. https://arxiv.org/html/2410.21596v1 (Retrieved: 2026-03-12)

[4] Delgado-Bravo, I. et al. "From Lived Experience to Insight: Unpacking the Psychological Risks of Using AI Conversational Agents." arXiv:2412.07951. https://arxiv.org/html/2412.07951v3 (Retrieved: 2026-03-12)

[5] Character.AI. "How Character.AI Prioritizes Teen Safety." https://blog.character.ai/how-character-ai-prioritizes-teen-safety/ (Retrieved: 2026-03-12)

[6] El-Seoud, S.A. et al. "The Impacts of Large Language Model Addiction on University Students' Mental Health: Gender as a Moderator." Algorithms, 18(12), 789. https://www.mdpi.com/1999-4893/18/12/789 (Retrieved: 2026-03-12)

[7] "Teammate Ontology: Domain Model for Team Members." Internal design document, 2026-03-11. (Unpublished — user profile pattern with structured identity fields + freeform LLM-readable description)

[8] Safe LLM Project. "Risk Assessment." `research/risk-assessment.md` (shared research document)

[9] Pedersen, S. et al. "Active nudging towards digital well-being: reducing excessive screen time." Frontiers in Psychiatry, 2025. https://pmc.ncbi.nlm.nih.gov/articles/PMC12310694/ (Retrieved: 2026-03-12)

[10] Cho, Y. et al. "In my defense, only three hours on Instagram: Designing Toward Digital Self-Awareness and Wellbeing." arXiv:2509.21860. https://arxiv.org/html/2509.21860v1 (Retrieved: 2026-03-12)

[11] JMIR Formative Research. "Toward Research-Informed Design Implications for Interventions Limiting Smartphone Use." https://formative.jmir.org/2022/4/e31730 (Retrieved: 2026-03-12)

[12] Character.AI. "Introducing Parental Insights: Enhanced Safety for Teens." https://blog.character.ai/introducing-parental-insights-enhanced-safety-for-teens/ (Retrieved: 2026-03-12)

[13] Anthropic. "Clio: Privacy-preserving insights into real-world AI use." https://www.anthropic.com/research/clio (Retrieved: 2026-03-12)

[14] Bellan, R. "OpenAI rolls out safety routing system, parental controls on ChatGPT." TechCrunch, Sep 2025. https://techcrunch.com/2025/09/29/openai-rolls-out-safety-routing-system-parental-controls-on-chatgpt/ (Retrieved: 2026-03-12)

[15] Langfuse. "Sessions (Chats, Threads, etc.)." https://langfuse.com/docs/observability/features/sessions (Retrieved: 2026-03-12)

[16] Langfuse. "User Tracking." https://langfuse.com/docs/observability/features/users (Retrieved: 2026-03-12)

[17] LiteLLM. "Custom Guardrail." https://docs.litellm.ai/docs/proxy/guardrails/custom_guardrail (Retrieved: 2026-03-12)

[18] LiteLLM. "Custom Code Guardrail." https://docs.litellm.ai/docs/proxy/guardrails/custom_code_guardrail (Retrieved: 2026-03-12)
