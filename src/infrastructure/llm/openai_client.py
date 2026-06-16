"""OpenAI-compatible LLM adapter (implements the `SqlGenerator` port).

Talks to any server exposing POST {base_url}/chat/completions. Uses a shared
httpx.AsyncClient (created at app startup, closed at shutdown).

Resilience contract (see app/domain/exceptions.py):
  - timeout / connection error / 5xx  -> raise LLMUnavailableError
  - 4xx (bad key, bad request)         -> raise LLMUnavailableError (detail=body)
  - reply not parseable into SQL       -> raise LLMResponseError

STATUS: skeleton. Method bodies are specified below for the implementer.
"""

from __future__ import annotations

import json
import logging
import re
import time

import httpx

from src.domain.entities import DatabaseSchema, GeneratedSql
from src.domain.exceptions import LLMResponseError, LLMUnavailableError
from src.infrastructure.config import Settings
from src.infrastructure.llm.prompt import build_messages
from src.infrastructure.observability.metrics import (
    llm_latency_seconds,
    llm_requests_total,
    llm_tokens_total,
)

logger = logging.getLogger(__name__)


class OpenAICompatibleClient:
    def __init__(self, settings: Settings, http_client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._http = http_client

    async def generate_sql(self, question: str, schema: DatabaseSchema) -> GeneratedSql:
        """Implement:

        1. messages = build_messages(question, schema)
        2. payload = {
               "model": settings.llm_model,
               "messages": messages,
               "temperature": settings.llm_temperature,
               "max_tokens": settings.llm_max_tokens,
               "response_format": {"type": "json_object"},  # best-effort
           }
        3. headers = {"Authorization": f"Bearer {settings.llm_api_key}"} if key else {}
        4. POST f"{settings.llm_base_url}/chat/completions" with payload/headers,
           timeout=settings.llm_timeout_seconds.
           - On httpx.TimeoutException / httpx.TransportError -> LLMUnavailableError
           - response.status_code >= 400 -> LLMUnavailableError(detail=response.text)
        5. content = data["choices"][0]["message"]["content"]
           - KeyError/IndexError/JSONDecodeError -> LLMResponseError
        6. return self._parse_sql(content)
        """
        messages = build_messages(question, schema)
        payload: dict[str, object] = {
            "model": self._settings.llm_model,
            "messages": messages,
            "temperature": self._settings.llm_temperature,
            "max_tokens": self._settings.llm_max_tokens,
            "response_format": {"type": "json_object"},
        }
        headers: dict[str, str] = {}
        if self._settings.llm_api_key:
            headers["Authorization"] = f"Bearer {self._settings.llm_api_key}"

        last_parse_error: LLMResponseError | None = None
        for attempt in range(2):
            started = time.perf_counter()
            try:
                response = await self._http.post(
                    f"{self._settings.llm_base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=self._settings.llm_timeout_seconds,
                )
            except httpx.TimeoutException as err:
                logger.warning("event=llm_request outcome=timeout")
                llm_requests_total.labels(outcome="timeout").inc()
                raise LLMUnavailableError("LLM request timed out") from err
            except httpx.TransportError as err:
                logger.warning("event=llm_request outcome=transport_error detail=%r", str(err))
                llm_requests_total.labels(outcome="transport_error").inc()
                raise LLMUnavailableError("LLM connection failed") from err
            finally:
                llm_latency_seconds.observe(time.perf_counter() - started)

            if response.status_code >= 400:
                logger.warning(
                    "event=llm_request outcome=http_error status=%d",
                    response.status_code,
                )
                llm_requests_total.labels(outcome="http_error").inc()
                raise LLMUnavailableError(
                    f"LLM returned HTTP {response.status_code}", detail=response.text
                )

            try:
                data = response.json()
                content = self._extract_content(data)
                self._record_usage(data)
                logger.info("event=llm_request outcome=success")
                llm_requests_total.labels(outcome="success").inc()
                return self._parse_sql(content)
            except LLMResponseError as err:
                last_parse_error = err
                logger.warning("event=llm_request outcome=bad_response detail=%r", err.message)
                llm_requests_total.labels(outcome="bad_response").inc()
                if attempt == 0:
                    logger.warning(
                        "LLM returned unparsable chat completion; retrying once",
                        extra={"attempt": attempt + 1},
                    )
                    continue
                raise
            except json.JSONDecodeError as err:
                logger.warning("event=llm_request outcome=json_decode_error")
                llm_requests_total.labels(outcome="json_decode_error").inc()
                raise LLMResponseError("LLM response was not valid JSON") from err

        assert last_parse_error is not None
        raise last_parse_error

    @staticmethod
    def _record_usage(data: object) -> None:
        if not isinstance(data, dict):
            return
        usage = data.get("usage")
        if not isinstance(usage, dict):
            return

        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        total_tokens = usage.get("total_tokens")

        if isinstance(prompt_tokens, int):
            llm_tokens_total.labels(kind="prompt").inc(prompt_tokens)
        if isinstance(completion_tokens, int):
            llm_tokens_total.labels(kind="completion").inc(completion_tokens)
        if isinstance(total_tokens, int):
            llm_tokens_total.labels(kind="total").inc(total_tokens)

    @staticmethod
    def _extract_content(data: object) -> str:
        if not isinstance(data, dict):
            raise LLMResponseError("Could not parse LLM response structure")

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LLMResponseError("Could not parse LLM response structure")

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise LLMResponseError("Could not parse LLM response structure")

        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise LLMResponseError("Could not parse LLM response structure")

        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise LLMResponseError(
                "LLM returned empty or non-text content",
                detail=json.dumps(message, ensure_ascii=False),
            )
        return content

    @staticmethod
    def _parse_sql(content: str) -> GeneratedSql:
        """Extract SQL from the model's reply, tolerant of non-JSON outputs.

        Implement (in order):
          1. Try json.loads(content); if it has a "sql" key, use it +
             optional "explanation".
          2. Else, if the content contains a ```sql ... ``` (or ``` ... ```)
             fence, take its inner text as the SQL.
          3. Else, treat the whole trimmed content as the SQL.
          4. If the resulting SQL string is empty -> raise LLMResponseError.
        Return GeneratedSql(sql=..., explanation=...).

        (The SqlGuard strips fences again defensively, so being lenient here is
        safe.)
        """
        # 1. Try JSON first.
        # Use raw_decode so that trailing garbage emitted by runaway models
        # (e.g. thousands of '{' after the closing '}') is silently ignored.
        try:
            data, _ = json.JSONDecoder().raw_decode(content.strip())
            if isinstance(data, dict) and "sql" in data:
                sql: str = str(data["sql"]).strip()
                raw_explanation = data.get("explanation")
                # Coerce to str | None so a non-string value can't break the
                # response model downstream.
                explanation: str | None = (
                    str(raw_explanation) if raw_explanation is not None else None
                )
                if not sql:
                    raise LLMResponseError("LLM returned empty SQL in JSON")
                return GeneratedSql(sql=sql, explanation=explanation)
        except json.JSONDecodeError:
            pass

        # 2. Fenced code block (```sql ... ``` or ``` ... ```)
        fence_match = re.search(r"```(?:sql)?\s*(.*?)\s*```", content, re.DOTALL)
        if fence_match:
            sql = fence_match.group(1).strip()
            if sql:
                return GeneratedSql(sql=sql, explanation=None)

        # 3. Raw fallback
        sql = content.strip()
        if not sql:
            raise LLMResponseError("LLM returned an empty response")
        return GeneratedSql(sql=sql, explanation=None)
