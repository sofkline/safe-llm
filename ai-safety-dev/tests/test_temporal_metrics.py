"""Tests for Stage 1: Temporal metrics computation."""

import pytest
from datetime import datetime, timedelta, UTC

from behavioral.temporal import _extract_last_user_message


class TestExtractLastUserMessage:
    def test_extracts_last_user_message(self):
        messages = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "response"},
            {"role": "user", "content": "second"},
        ]
        assert _extract_last_user_message(messages) == "second"

    def test_single_user_message(self):
        messages = [{"role": "user", "content": "only one"}]
        assert _extract_last_user_message(messages) == "only one"

    def test_no_user_messages(self):
        messages = [{"role": "assistant", "content": "response"}]
        assert _extract_last_user_message(messages) is None

    def test_empty_messages(self):
        assert _extract_last_user_message([]) is None

    def test_none_messages(self):
        assert _extract_last_user_message(None) is None

    def test_messages_as_dict(self):
        """messages field might be a dict instead of list in edge cases."""
        assert _extract_last_user_message({}) is None
