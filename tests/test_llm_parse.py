"""Unit tests for OpenAICompatibleClient._parse_sql() — no network needed."""

from __future__ import annotations

import pytest

from src.domain.exceptions import LLMResponseError
from src.infrastructure.llm.openai_client import OpenAICompatibleClient


def test_parse_clean_json() -> None:
    result = OpenAICompatibleClient._parse_sql(
        '{"sql": "SELECT 1", "explanation": "trivial"}'
    )
    assert result.sql == "SELECT 1"
    assert result.explanation == "trivial"


def test_parse_json_without_explanation() -> None:
    result = OpenAICompatibleClient._parse_sql('{"sql": "SELECT id FROM orders"}')
    assert result.sql == "SELECT id FROM orders"
    assert result.explanation is None


def test_parse_fenced_sql_block() -> None:
    content = "```sql\nSELECT * FROM customers\n```"
    result = OpenAICompatibleClient._parse_sql(content)
    assert result.sql == "SELECT * FROM customers"


def test_parse_plain_fenced_block() -> None:
    content = "```\nSELECT count(*) FROM orders\n```"
    result = OpenAICompatibleClient._parse_sql(content)
    assert result.sql == "SELECT count(*) FROM orders"


def test_parse_raw_sql_fallback() -> None:
    result = OpenAICompatibleClient._parse_sql("SELECT id FROM items WHERE id = 1")
    assert result.sql == "SELECT id FROM items WHERE id = 1"
    assert result.explanation is None


def test_parse_empty_string_raises() -> None:
    with pytest.raises(LLMResponseError):
        OpenAICompatibleClient._parse_sql("")


def test_parse_whitespace_only_raises() -> None:
    with pytest.raises(LLMResponseError):
        OpenAICompatibleClient._parse_sql("   \n  ")


def test_parse_json_with_empty_sql_raises() -> None:
    with pytest.raises(LLMResponseError):
        OpenAICompatibleClient._parse_sql('{"sql": ""}')


def test_extract_content_from_standard_chat_response() -> None:
    content = OpenAICompatibleClient._extract_content(
        {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": '{"sql":"SELECT 1"}',
                    }
                }
            ]
        }
    )
    assert content == '{"sql":"SELECT 1"}'


def test_extract_content_with_null_content_raises() -> None:
    with pytest.raises(LLMResponseError, match="empty or non-text"):
        OpenAICompatibleClient._extract_content(
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "refusal": None,
                            "reasoning": None,
                        }
                    }
                ]
            }
        )
