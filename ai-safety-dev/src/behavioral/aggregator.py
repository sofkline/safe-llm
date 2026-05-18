"""Главный конвейер: запускается ежедневно для каждого пользователя, выполняет Этапы 1-4."""

import logging
from datetime import datetime, date, UTC

from behavioral.models import (
    UserBehaviorProfile,
    MetricsHistory,
    DailySummary,
    BehavioralEvent,
)
from behavioral.repository import BehavioralRepository
from behavioral.temporal import compute_temporal_metrics, compute_baselines, compute_trend_flags
from behavioral.danger_agg import compute_danger_class_agg
from behavioral.behavioral_llm import compute_behavioral_scores_and_summary
from behavioral.risk_engine import evaluate_risk_zone

logger = logging.getLogger(__name__)


async def run_aggregator_for_user(end_user_id: str) -> None:
    """Execute the full 4-stage pipeline for a single user.

    1. Stage 1: Temporal metrics (pure SQL from SpendLogs)
    2. Stage 2: Danger class aggregation (pure SQL from PredictTable)
    3. Stage 3: Behavioral LLM scores + daily summary
    4. Stage 4: Risk zone engine

    After all stages: write MetricsHistory, DailySummary, update UserBehaviorProfile,
    and optionally write BehavioralEvent if zone changed.
    """
    repo = BehavioralRepository()
    now = datetime.utcnow()
    today = now.date()

    logger.info("Aggregator starting for user %s", end_user_id)

    # Этап 1: темпоральные метрики из SpendLogs (кол-во сообщений, ночная активность и т.д.)
    temporal_metrics = await compute_temporal_metrics(end_user_id)
    logger.info("Stage 1 complete for %s", end_user_id)

    # Если пользователь не писал сегодня — пропускаем, зона риска остаётся прежней
    if temporal_metrics.get("daily_message_count", 0) == 0:
        logger.info("No messages today for %s, skipping aggregation (zone preserved)", end_user_id)
        return

    # Базовые линии: скользящее среднее за 7 дней для обнаружения трендов
    recent_history = await repo.get_recent_metrics(end_user_id, days=7)
    past_temporal = [h.temporal_metrics for h in recent_history if h.temporal_metrics]
    baselines = compute_baselines(past_temporal)
    trend_flags = compute_trend_flags(temporal_metrics, baselines)
    if trend_flags:
        logger.info("Trend flags for %s: %s", end_user_id, trend_flags)

    # Этап 2: агрегация классов опасности из PredictTable (suicide, psychosis и др.)
    danger_class_agg = await compute_danger_class_agg(end_user_id)
    logger.info("Stage 2 complete for %s", end_user_id)

    # Этап 3: LLM-анализ поведения + дневная сводка + календарь
    stage3_result = await compute_behavioral_scores_and_summary(end_user_id, today)
    behavioral_scores = stage3_result["scores"]
    summary_data = stage3_result["summary"]
    logger.info("Stage 3 complete for %s", end_user_id)

    # Этап 4: правила определения зоны GREEN/YELLOW/RED
    risk_zone, triggered_rules = await evaluate_risk_zone(
        temporal_metrics, danger_class_agg, behavioral_scores,
        baselines=baselines,
        recent_history=recent_history,
    )
    logger.info("Stage 4 complete for %s: zone=%s, triggers=%s", end_user_id, risk_zone, triggered_rules)

    # --- Запись результатов в БД ---

    # 1. MetricsHistory — ежедневный снимок всех метрик
    metrics_entry = MetricsHistory(
        end_user_id=end_user_id,
        computed_at=now,
        period_type="daily",
        temporal_metrics=temporal_metrics,
        danger_class_agg=danger_class_agg,
        behavioral_scores=behavioral_scores,
        risk_zone=risk_zone,
    )
    await repo.add_metrics_history(metrics_entry)

    # 2. DailySummary — темы дня, события, цитаты, маркеры отношений с AI
    is_notable = _compute_is_notable(summary_data, behavioral_scores)
    daily_summary = DailySummary(
        end_user_id=end_user_id,
        summary_date=today,
        key_topics=summary_data["key_topics"],
        life_events=summary_data["life_events"],
        emotional_tone=summary_data["emotional_tone"],
        ai_relationship_markers=summary_data["ai_relationship_markers"],
        notable_quotes=summary_data["notable_quotes"],
        operator_note=summary_data["operator_note"],
        is_notable=is_notable,
    )
    await repo.add_daily_summary(daily_summary)

    # 3. UserBehaviorProfile — текущее состояние пользователя (upsert)
    old_profile = await repo.get_profile(end_user_id)
    old_zone = old_profile.risk_zone if old_profile else "GREEN"

    profile = UserBehaviorProfile(
        end_user_id=end_user_id,
        risk_zone=risk_zone,
        danger_class_scores=danger_class_agg,
        behavioral_scores=behavioral_scores,
        temporal_summary=temporal_metrics,
        temporal_baselines=baselines,
        last_assessed_at=now,
        updated_at=now,
    )
    await repo.upsert_profile(profile)

    # 4. BehavioralEvent — фиксируем переходы зон и RED-алерты
    if risk_zone != old_zone or risk_zone == "RED":
        event = BehavioralEvent(
            end_user_id=end_user_id,
            detected_at=now,
            event_type="risk_zone_change",
            severity=risk_zone,
            details={
                "old_zone": old_zone,
                "new_zone": risk_zone,
                "triggered_rules": triggered_rules,
            },
        )
        await repo.add_event(event)
        logger.info("Zone change event: %s -> %s for %s", old_zone, risk_zone, end_user_id)

    # 5. Дублируем скоры в Langfuse для дашборда (best-effort, не блокирует)
    from behavioral.langfuse_scores import write_behavioral_scores_to_langfuse
    await write_behavioral_scores_to_langfuse(
        end_user_id, risk_zone, behavioral_scores, danger_class_agg
    )

    logger.info("Aggregator complete for user %s", end_user_id)


def _compute_is_notable(summary_data: dict, behavioral_scores: dict) -> bool:
    """Determine if today's summary is notable for calendar filtering."""
    if summary_data.get("life_events"):
        return True
    if summary_data.get("ai_relationship_markers"):
        return True
    tone = summary_data.get("emotional_tone", "neutral").lower().strip()
    if tone not in ("neutral", "calm", "normal"):
        return True
    if behavioral_scores.get("topic_concentration", 0) > 0.7:
        return True
    if behavioral_scores.get("decision_delegation", 0) > 0.4:
        return True
    return False
