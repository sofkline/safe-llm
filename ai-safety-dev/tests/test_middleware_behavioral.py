"""Tests for soft middleware — risk zone prompt injection."""

import pytest
from middleware import _inject_risk_zone_prompt


class TestRiskZonePromptInjection:
    def test_green_no_injection(self):
        messages = [{"role": "user", "content": "Hello"}]
        result = _inject_risk_zone_prompt(messages, "GREEN")
        assert result == messages
        assert len(result) == 1

    def test_yellow_prepends_system_message(self):
        messages = [{"role": "user", "content": "Hello"}]
        result = _inject_risk_zone_prompt(messages, "YELLOW")
        assert len(result) == 2
        assert result[0]["role"] == "system"
        assert "unhealthy interaction pattern" in result[0]["content"]
        assert result[1] == {"role": "user", "content": "Hello"}

    def test_red_prepends_system_message(self):
        messages = [{"role": "user", "content": "Hello"}]
        result = _inject_risk_zone_prompt(messages, "RED")
        assert len(result) == 2
        assert result[0]["role"] == "system"
        assert "emotional distress" in result[0]["content"]

    def test_none_zone_no_injection(self):
        messages = [{"role": "user", "content": "Hello"}]
        result = _inject_risk_zone_prompt(messages, None)
        assert result == messages

    def test_preserves_existing_system_message(self):
        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello"},
        ]
        result = _inject_risk_zone_prompt(messages, "RED")
        assert len(result) == 3
        assert result[0]["role"] == "system"
        assert "emotional distress" in result[0]["content"]
        assert result[1] == {"role": "system", "content": "You are a helpful assistant"}
