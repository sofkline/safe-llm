"""Tests for Stage 2: Danger class aggregation."""

import pytest
from datetime import datetime, UTC
from unittest.mock import patch

from behavioral.danger_agg import (
    compute_danger_class_agg,
    _aggregate_predictions,
    _parse_predict_json,
)

CLASSES = ["self_harm", "psychosis", "delusion", "obsession", "anthropomorphism"]


class TestParsePredictJson:
    def test_parses_valid_predict(self):
        predict_json = {
            "predict": {
                "self_harm": {"label": 0, "confidence": 0.1},
                "psychosis": {"label": 0, "confidence": 0.2},
                "delusion": {"label": 1, "confidence": 0.7},
                "obsession": {"label": 1, "confidence": 0.8},
                "anthropomorphism": {"label": 0, "confidence": 0.3},
            }
        }
        result = _parse_predict_json(predict_json)
        assert result["self_harm"] == {"label": 0, "confidence": 0.1}
        assert result["delusion"] == {"label": 1, "confidence": 0.7}

    def test_returns_none_for_invalid_json(self):
        assert _parse_predict_json(None) is None
        assert _parse_predict_json({}) is None
        assert _parse_predict_json({"predict": "not a dict"}) is None

    def test_missing_class_returns_none(self):
        predict_json = {"predict": {"self_harm": {"label": 0, "confidence": 0.1}}}
        result = _parse_predict_json(predict_json)
        assert result is not None
        assert "self_harm" in result


class TestAggregatePredictions:
    def test_single_prediction(self):
        predictions = [
            {
                "suicide": {"label": 0, "confidence": 0.1},
                "psychosis": {"label": 0, "confidence": 0.2},
                "depression": {"label": 1, "confidence": 0.7},
                "obsession": {"label": 0, "confidence": 0.3},
                "anthropomorphism": {"label": 0, "confidence": 0.4},
            }
        ]
        result = _aggregate_predictions(predictions)
        # label=0 classes contribute 0 danger regardless of confidence
        assert result["suicide_avg"] == 0.0
        assert result["suicide_max"] == 0.0
        assert result["suicide_flag_rate"] == 0.0
        # label=1 class keeps its confidence as severity
        assert result["depression_avg"] == 0.7
        assert result["depression_flag_rate"] == 1.0

    def test_multiple_predictions(self):
        predictions = [
            {
                "suicide": {"label": 1, "confidence": 0.9},
                "psychosis": {"label": 0, "confidence": 0.1},
                "depression": {"label": 0, "confidence": 0.2},
                "obsession": {"label": 0, "confidence": 0.1},
                "anthropomorphism": {"label": 0, "confidence": 0.1},
            },
            {
                "suicide": {"label": 0, "confidence": 0.3},
                "psychosis": {"label": 0, "confidence": 0.3},
                "depression": {"label": 1, "confidence": 0.8},
                "obsession": {"label": 0, "confidence": 0.2},
                "anthropomorphism": {"label": 0, "confidence": 0.2},
            },
        ]
        result = _aggregate_predictions(predictions)
        # suicide: [label1 conf0.9, label0 conf0.3] -> gated [0.9, 0.0]
        assert result["suicide_avg"] == pytest.approx(0.45, abs=0.01)
        assert result["suicide_max"] == 0.9
        assert result["suicide_flag_rate"] == 0.5
        assert result["depression_flag_rate"] == 0.5
        # suicide avg 0.45 is the highest class avg
        assert result["max_class_avg"] == pytest.approx(0.45, abs=0.01)

    def test_empty_predictions(self):
        result = _aggregate_predictions([])
        assert result["suicide_avg"] == 0.0
        assert result["max_class_avg"] == 0.0

    def test_max_class_avg(self):
        """max_class_avg should be the highest avg across all 5 classes."""
        predictions = [
            {
                "suicide": {"label": 0, "confidence": 0.1},
                "psychosis": {"label": 0, "confidence": 0.1},
                "depression": {"label": 1, "confidence": 0.9},
                "obsession": {"label": 0, "confidence": 0.1},
                "anthropomorphism": {"label": 0, "confidence": 0.1},
            },
        ]
        result = _aggregate_predictions(predictions)
        assert result["max_class_avg"] == 0.9

    def test_label0_high_confidence_is_gated(self):
        """Regression: a model confident a class is ABSENT (label=0 with high
        confidence) must contribute 0 danger, not its confidence value.

        gpt-oss-120b emitted label=0/confidence=0.96 for every class on benign
        input (reading "confidence" as confidence-in-its-decision). Ungated
        aggregation turned that into suicide_max=0.96, and the Stage-4 risk
        engine fired RED on clean GREEN days."""
        predictions = [
            {c: {"label": 0, "confidence": 0.96} for c in
             ["suicide", "psychosis", "depression", "obsession", "anthropomorphism"]}
        ]
        result = _aggregate_predictions(predictions)
        assert result["suicide_max"] == 0.0
        assert result["psychosis_max"] == 0.0
        assert result["suicide_avg"] == 0.0
        assert result["max_class_avg"] == 0.0

    def test_degenerate_all_zero_confidence_prediction_is_dropped(self):
        """Regression: gpt-oss-120b occasionally returns predictions where
        every class has confidence==0 — a parser-fallback / malformed API
        response. A `{label:1, confidence:0.0}` in such a response previously
        counted toward suicide_flag_rate and fired RED on benign content
        (Dmitry day 11 hour 16, a benign gym/Garmin conversation).
        Degenerate predictions are now dropped before aggregation."""
        degenerate = {
            "suicide":   {"label": 1, "confidence": 0.0},
            "psychosis": {"label": 0, "confidence": 0.0},
            "depression":{"label": 0, "confidence": 0.0},
            "obsession": {"label": 0, "confidence": 0.0},
            "anthropomorphism": {"label": 0, "confidence": 0.0},
        }
        result = _aggregate_predictions([degenerate])
        # Treated as zero predictions: all aggregates are zero.
        assert result["suicide_flag_rate"] == 0.0
        assert result["suicide_max"] == 0.0
        assert result["max_class_avg"] == 0.0

    def test_degenerate_does_not_pollute_real_predictions(self):
        """One degenerate + one good prediction should yield the same result
        as the good prediction alone (degenerate dropped, not blended in)."""
        good = {
            "suicide":   {"label": 1, "confidence": 0.8},
            "psychosis": {"label": 0, "confidence": 0.9},
            "depression":{"label": 0, "confidence": 0.9},
            "obsession": {"label": 0, "confidence": 0.9},
            "anthropomorphism": {"label": 0, "confidence": 0.9},
        }
        degenerate = {c: {"label": 0, "confidence": 0.0} for c in
                      ["suicide", "psychosis", "depression", "obsession", "anthropomorphism"]}
        result_mixed = _aggregate_predictions([good, degenerate])
        result_clean = _aggregate_predictions([good])
        assert result_mixed["suicide_flag_rate"] == result_clean["suicide_flag_rate"]
        assert result_mixed["suicide_max"] == result_clean["suicide_max"]
        assert result_mixed["suicide_avg"] == result_clean["suicide_avg"]


class TestComputeDangerClassAgg:
    @pytest.mark.asyncio
    async def test_no_predictions_returns_zeros(self):
        with patch("behavioral.danger_agg._fetch_predict_rows", return_value=[]):
            result = await compute_danger_class_agg("user1")
        assert result["suicide_avg"] == 0.0
        assert result["max_class_avg"] == 0.0

    @pytest.mark.asyncio
    async def test_aggregates_from_db_rows(self):
        rows = [
            {
                "predict": {
                    "suicide": {"label": 1, "confidence": 0.8},
                    "psychosis": {"label": 0, "confidence": 0.1},
                    "depression": {"label": 0, "confidence": 0.2},
                    "obsession": {"label": 0, "confidence": 0.3},
                    "anthropomorphism": {"label": 0, "confidence": 0.1},
                }
            },
            {
                "predict": {
                    "suicide": {"label": 0, "confidence": 0.2},
                    "psychosis": {"label": 0, "confidence": 0.3},
                    "depression": {"label": 1, "confidence": 0.6},
                    "obsession": {"label": 0, "confidence": 0.1},
                    "anthropomorphism": {"label": 0, "confidence": 0.2},
                }
            },
        ]
        with patch("behavioral.danger_agg._fetch_predict_rows", return_value=rows):
            result = await compute_danger_class_agg("user1")
        # suicide: [label1 conf0.8, label0 conf0.2] -> gated [0.8, 0.0]
        assert result["suicide_avg"] == pytest.approx(0.4, abs=0.01)
        assert result["suicide_max"] == 0.8
        assert result["suicide_flag_rate"] == 0.5

    @pytest.mark.asyncio
    async def test_skips_invalid_predict_json(self):
        rows = [
            None,
            {"predict": "not_a_dict"},
            {
                "predict": {
                    "suicide": {"label": 0, "confidence": 0.5},
                    "psychosis": {"label": 0, "confidence": 0.1},
                    "depression": {"label": 0, "confidence": 0.1},
                    "obsession": {"label": 0, "confidence": 0.1},
                    "anthropomorphism": {"label": 0, "confidence": 0.1},
                }
            },
        ]
        with patch("behavioral.danger_agg._fetch_predict_rows", return_value=rows):
            result = await compute_danger_class_agg("user1")
        # the only valid row has suicide label=0 -> gated to 0.0
        assert result["suicide_avg"] == 0.0
