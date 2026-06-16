"""Prompt construction for text-to-SQL.

The prompt is the product. Keep it here, version it, and keep it deterministic.
We ask the model to return STRICT JSON so parsing is robust across providers
(some models ignore `response_format`, so the client also tolerates a fenced
SQL block — see openai_client.py).

Fully implemented: prompt wording is a core design decision.
"""

from __future__ import annotations

from src.domain.entities import DatabaseSchema

SYSTEM_PROMPT = """\
You are a senior data analyst who writes PostgreSQL queries.

You are given the schema of a PostgreSQL database and a question in natural
language. Produce ONE SQL query that answers the question.

Hard rules:
- Dialect is PostgreSQL.
- Output exactly ONE statement. It MUST be a read-only SELECT (a leading WITH
  CTE is fine). Never write INSERT, UPDATE, DELETE, or any DDL.
- Use ONLY the tables and columns provided in the schema. Never invent names.
- Prefer explicit JOINs over implicit ones. Qualify ambiguous columns.
- When the question implies ranking or "top N", add ORDER BY and LIMIT.
- If the question is ambiguous, make the most reasonable analytical assumption.
- Do not add comments or explanations inside the SQL.

Respond with STRICT JSON and nothing else, in this exact shape:
{"sql": "<the query>", "explanation": "<one short sentence>"}
"""

_USER_TEMPLATE = """\
Database schema:
{schema}

Question:
{question}

Return only the JSON object.
"""


def build_messages(question: str, schema: DatabaseSchema) -> list[dict[str, str]]:
    """Build the OpenAI `messages` array for the chat/completions request."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": _USER_TEMPLATE.format(
                schema=schema.render_for_prompt(),
                question=question.strip(),
            ),
        },
    ]
