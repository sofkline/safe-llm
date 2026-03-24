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
                "self_harm": {"label": 0, "confidence": 0.1},
                "psychosis": {"label": 0, "confidence": 0.2},
                "delusion": {"label": 1, "confidence": 0.7},
                "obsession": {"label": 0, "confidence": 0.3},
                "anthropomorphism": {"label": 0, "confidence": 0.4},
            }
        ]
        result = _aggregate_predictions(predictions)
        assert result["self_harm_avg"] == 0.1
        assert result["self_harm_max"] == 0.1
        assert result["self_harm_flag_rate"] == 0.0
        assert result["delusion_avg"] == 0.7
        assert result["delusion_flag_rate"] == 1.0

    def test_multiple_predictions(self):
        predictions = [
            {
                "self_harm": {"label": 1, "confidence": 0.9},
                "psychosis": {"label": 0, "confidence": 0.1},
                "delusion": {"label": 0, "confidence": 0.2},
                "obsession": {"label": 0, "confidence": 0.1},
                "anthropomorphism": {"label": 0, "confidence": 0.1},
            },
            {
                "self_harm": {"label": 0, "confidence": 0.3},
                "psychosis": {"label": 0, "confidence": 0.3},
                "delusion": {"label": 1, "confidence": 0.8},
                "obsession": {"label": 0, "confidence": 0.2},
                "anthropomorphism": {"label": 0, "confidence": 0.2},
            },
        ]
        result = _aggregate_predictions(predictions)
        assert result["self_harm_avg"] == pytest.approx(0.6, abs=0.01)
        assert result["self_harm_max"] == 0.9
        assert result["self_harm_flag_rate"] == 0.5
        assert result["delusion_flag_rate"] == 0.5
        assert result["max_class_avg"] == pytest.approx(0.6, abs=0.01)

    def test_empty_predictions(self):
        result = _aggregate_predictions([])
        assert result["self_harm_avg"] == 0.0
        assert result["max_class_avg"] == 0.0

    def test_max_class_avg(self):
        """max_class_avg should be the highest avg across all 5 classes."""
        predictions = [
            {
                "self_harm": {"label": 0, "confidence": 0.1},
                "psychosis": {"label": 0, "confidence": 0.1},
                "delusion": {"label": 0, "confidence": 0.1},
                "obsession": {"label": 0, "confidence": 0.1},
                "anthropomorphism": {"label": 0, "confidence": 0.9},
            },
        ]
        result = _aggregate_predictions(predictions)
        assert result["max_class_avg"] == 0.9


class TestComputeDangerClassAgg:
    @pytest.mark.asyncio
    async def test_no_predictions_returns_zeros(self):
        with patch("behavioral.danger_agg._fetch_predict_rows", return_value=[]):
            result = await compute_danger_class_agg("user1")
        assert result["self_harm_avg"] == 0.0
        assert result["max_class_avg"] == 0.0

    @pytest.mark.asyncio
    async def test_aggregates_from_db_rows(self):
        rows = [
            {
                "predict": {
                    "self_harm": {"label": 1, "confidence": 0.8},
                    "psychosis": {"label": 0, "confidence": 0.1},
                    "delusion": {"label": 0, "confidence": 0.2},
                    "obsession": {"label": 0, "confidence": 0.3},
                    "anthropomorphism": {"label": 0, "confidence": 0.1},
                }
            },
            {
                "predict": {
                    "self_harm": {"label": 0, "confidence": 0.2},
                    "psychosis": {"label": 0, "confidence": 0.3},
                    "delusion": {"label": 1, "confidence": 0.6},
                    "obsession": {"label": 0, "confidence": 0.1},
                    "anthropomorphism": {"label": 0, "confidence": 0.2},
                }
            },
        ]
        with patch("behavioral.danger_agg._fetch_predict_rows", return_value=rows):
            result = await compute_danger_class_agg("user1")
        assert result["self_harm_avg"] == pytest.approx(0.5, abs=0.01)
        assert result["self_harm_max"] == 0.8
        assert result["self_harm_flag_rate"] == 0.5

    @pytest.mark.asyncio
    async def test_skips_invalid_predict_json(self):
        rows = [
            None,
            {"predict": "not_a_dict"},
            {
                "predict": {
                    "self_harm": {"label": 0, "confidence": 0.5},
                    "psychosis": {"label": 0, "confidence": 0.1},
                    "delusion": {"label": 0, "confidence": 0.1},
                    "obsession": {"label": 0, "confidence": 0.1},
                    "anthropomorphism": {"label": 0, "confidence": 0.1},
                }
            },
        ]
        with patch("behavioral.danger_agg._fetch_predict_rows", return_value=rows):
            result = await compute_danger_class_agg("user1")
        assert result["self_harm_avg"] == 0.5
