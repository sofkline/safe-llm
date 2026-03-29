# 4 таблицы поведенческого мониторинга
from sqlalchemy import (
    Boolean, Date, DateTime, Integer, JSON, String, Text, text,
    UniqueConstraint,
)
from sqlalchemy.orm import mapped_column

from database.models import Base


class UserBehaviorProfile(Base):
    """Текущее состояние пользователя. Читается middleware и еженедельным отчётом."""

    __tablename__ = "UserBehaviorProfile"

    end_user_id = mapped_column(String, primary_key=True)
    risk_zone = mapped_column(String, nullable=False, server_default=text("'GREEN'"))
    danger_class_scores = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    behavioral_scores = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    temporal_summary = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    temporal_baselines = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    last_assessed_at = mapped_column(DateTime, nullable=True)
    updated_at = mapped_column(DateTime, nullable=True, server_default=text("CURRENT_TIMESTAMP"))


class MetricsHistory(Base):
    """Ежедневные снимки метрик для трендов и еженедельного отчёта."""

    __tablename__ = "MetricsHistory"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    end_user_id = mapped_column(String, nullable=False)
    computed_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    period_type = mapped_column(String, nullable=False, server_default=text("'daily'"))
    temporal_metrics = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    danger_class_agg = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    behavioral_scores = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    risk_zone = mapped_column(String, nullable=False, server_default=text("'GREEN'"))


class DailySummary(Base):
    """Дневная сводка: темы, события, цитаты, маркеры. Читается Этапом 3 (календарь)."""

    __tablename__ = "DailySummary"
    __table_args__ = (
        UniqueConstraint("end_user_id", "summary_date", name="uq_daily_summary_user_date"),
    )

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    end_user_id = mapped_column(String, nullable=False)
    summary_date = mapped_column(Date, nullable=False)
    key_topics = mapped_column(JSON, nullable=False, server_default=text("'[]'"))
    life_events = mapped_column(JSON, nullable=False, server_default=text("'[]'"))
    emotional_tone = mapped_column(String, nullable=False, server_default=text("'neutral'"))
    ai_relationship_markers = mapped_column(JSON, nullable=False, server_default=text("'[]'"))
    notable_quotes = mapped_column(JSON, nullable=False, server_default=text("'[]'"))
    operator_note = mapped_column(Text, nullable=True)
    is_notable = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))


class BehavioralEvent(Base):
    """События пересечения порогов и переходы зон риска."""

    __tablename__ = "BehavioralEvents"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    end_user_id = mapped_column(String, nullable=False)
    detected_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    event_type = mapped_column(String, nullable=False)
    severity = mapped_column(String, nullable=False)
    details = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    acknowledged = mapped_column(Boolean, nullable=False, server_default=text("false"))
