import json
import re
import time

from groq import Groq
from app.config import GROQ_API_KEY, WAREHOUSE_SCHEMA
from app.services.ai_monitor_service import (
    record_sql_generation,
    record_summary_generation,
)

client = Groq(api_key=GROQ_API_KEY)

MODEL_NAME = "llama-3.1-8b-instant"


def clean_sql(raw_sql: str) -> str:
    sql = raw_sql.strip()

    sql = sql.replace("```sql", "")
    sql = sql.replace("```", "")
    sql = re.sub(r"(?i)^sql\s*:", "", sql).strip()

    if ";" in sql:
        sql = sql.split(";")[0].strip() + ";"
    else:
        sql = sql + ";"

    return sql


def generate_sql(question, schema=None, table_name=None):
    prompt = f"""
You are an expert BigQuery SQL generator for a pharma analytics warehouse.

Use only this warehouse schema:

{WAREHOUSE_SCHEMA}

Rules:
- Return ONLY SQL.
- No markdown.
- No explanation.
- No comments.
- Use BigQuery Standard SQL.
- Only generate SELECT queries.
- Use fully qualified table names with backticks.
- Never use INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, MERGE, or CREATE.
- Do not invent tables or columns.
- Use LIMIT 100 unless the user asks for a specific limit.
- For aggregate queries, use GROUP BY and ORDER BY.
- For client-specific questions, join medicines_master with clients.
- For side effect questions, use medicine_side_effects and side_effects.
- For use/condition questions, use medicine_uses and uses.
- For substitute questions, use medicine_substitutes and substitutes.
- For chemical class questions, join using SAFE_CAST(m.chemical_class_id AS INT64).
- For action class questions, join using SAFE_CAST(m.action_class_id AS INT64).

Medical safety rule:
- Do not recommend medicines, dosage, prescriptions, or treatment decisions.
- Only generate analytics/reporting SQL.
- If the question asks for personal medical advice, do not generate SQL.

Example:
User: Show medicine count by client

SQL:
SELECT
  c.client_name,
  COUNT(*) AS medicine_count
FROM `pharma-ai-dashboard.Pharma_Warehouse.medicines_master` m
JOIN `pharma-ai-dashboard.Pharma_Warehouse.clients` c
  ON m.client_id = c.client_id
GROUP BY c.client_name
ORDER BY medicine_count DESC
LIMIT 100

Question:
{question}
"""

    start_time = time.time()

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )

        raw_sql = response.choices[0].message.content
        cleaned_sql = clean_sql(raw_sql)
        latency_ms = round((time.time() - start_time) * 1000, 2)

        record_sql_generation(
            model=MODEL_NAME,
            prompt_length=len(prompt),
            response_length=len(cleaned_sql),
            latency_ms=latency_ms,
            success=True,
        )

        return cleaned_sql

    except Exception as error:
        latency_ms = round((time.time() - start_time) * 1000, 2)

        record_sql_generation(
            model=MODEL_NAME,
            prompt_length=len(prompt),
            response_length=0,
            latency_ms=latency_ms,
            success=False,
            error_message=str(error),
        )

        raise error


def summarize_results(question, sql, data, insights):
    sample_data = json.dumps(data[:5], indent=2, default=str)

    if len(sample_data) > 2000:
        sample_data = sample_data[:2000]

    prompt = f"""
You are a careful pharma analytics assistant.

User question:
{question}

SQL used:
{sql}

Backend-computed insights:
{insights}

BigQuery result sample:
{sample_data}

Rules:
- Use ONLY the provided BigQuery data and backend insights.
- Do not invent medicines, counts, classes, uses, or side effects.
- If data is empty, say no matching records were found.
- Do not give medical advice, dosage instructions, prescriptions, or treatment recommendations.
- Keep the response concise and accurate.

Return format:
Direct Answer:
Key Insight:
"""

    start_time = time.time()

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )

        summary = response.choices[0].message.content.strip()
        latency_ms = round((time.time() - start_time) * 1000, 2)

        record_summary_generation(
            model=MODEL_NAME,
            prompt_length=len(prompt),
            response_length=len(summary),
            latency_ms=latency_ms,
            success=True,
        )

        return summary

    except Exception as error:
        latency_ms = round((time.time() - start_time) * 1000, 2)

        record_summary_generation(
            model=MODEL_NAME,
            prompt_length=len(prompt),
            response_length=0,
            latency_ms=latency_ms,
            success=False,
            error_message=str(error),
        )

        raise error