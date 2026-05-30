import json
import re
from groq import Groq
from app.config import GROQ_API_KEY

client = Groq(api_key=GROQ_API_KEY)

MODEL_NAME = "llama-3.1-8b-instant"


def clean_sql(raw_sql: str) -> str:
    sql = raw_sql.strip()

    sql = sql.replace("```sql", "")
    sql = sql.replace("```", "")
    sql = sql.strip()

    sql = re.sub(r"(?i)^sql\s*:", "", sql).strip()

    if ";" in sql:
        sql = sql.split(";")[0].strip() + ";"

    return sql


def generate_sql(question, schema, table_name):
    column_names = [field["name"] for field in schema]

    def col(preferred, fallback):
        if preferred in column_names:
            return f"`{preferred}`" if " " in preferred else preferred
        if fallback in column_names:
            return f"`{fallback}`" if " " in fallback else fallback
        return f"`{preferred}`" if " " in preferred else preferred

    name_col = col("name", "name")
    therapeutic_col = col("Therapeutic Class", "therapeutic_class")
    action_col = col("Action Class", "action_class")
    chemical_col = col("Chemical Class", "chemical_class")
    habit_col = col("Habit Forming", "habit_forming")

    side_effect_cols = [
        f"`{c}`" if " " in c else c
        for c in column_names
        if c.lower().startswith("sideeffect") or c.lower().startswith("side_effect")
    ]

    use_cols = [
        f"`{c}`" if " " in c else c
        for c in column_names
        if c.lower().startswith("use")
    ]

    substitute_cols = [
        f"`{c}`" if " " in c else c
        for c in column_names
        if c.lower().startswith("substitute")
    ]

    prompt = f"""
You are a strict BigQuery SQL generator for a medicine analytics database.

Actual table:
`{table_name}`

Schema:
{schema}

Use these exact columns:
- Medicine name column: {name_col}
- Therapeutic class column: {therapeutic_col}
- Action class column: {action_col}
- Chemical class column: {chemical_col}
- Habit forming column: {habit_col}
- Use columns: {use_cols}
- Substitute columns: {substitute_cols}
- Side effect columns: {side_effect_cols}

Your job:
Convert the user question into ONE valid BigQuery SELECT query.

STRICT OUTPUT RULES:
- Return ONLY SQL.
- No markdown.
- No explanation.
- No comments.
- Always use this exact table: `{table_name}`
- Always wrap the table name in backticks.
- Only SELECT queries are allowed.
- Always use LIMIT 100 for row-level/detail queries.
- Do not use LIMIT for aggregate/grouped count queries unless the user asks for top N.
- Use ONLY column names from the provided schema.
- Wrap column names with spaces in backticks.

TEXT MATCHING RULES:
- Use LOWER(CAST(column AS STRING)) LIKE '%value%' for text matching.
- Do not use exact equality for medicine names.
- For therapeutic classes, use LOWER(CAST({therapeutic_col} AS STRING)) LIKE '%value%'.
- For habit forming:
  - If the column is BOOLEAN, use {habit_col} = TRUE or {habit_col} = FALSE.
  - If the column is STRING, use LOWER(CAST({habit_col} AS STRING)) LIKE '%yes%' or '%true%'.

SIDE EFFECT RULES:
- For side effect searches, check all side effect columns listed above with OR.
- For "most side effects", calculate side_effect_count by summing all non-empty side effect fields.
- Never use COUNT(*) to count side effects.

MEDICINE USE RULES:
- For "used for" questions, check all use columns listed above with OR.
- For "what is X used for", select {name_col}, use columns, {therapeutic_col}, {action_col}.
- Use fuzzy matching on {name_col}.

AGGREGATION RULES:
- For count by category/class queries, include both the grouped column and COUNT(*) AS medicine_count.
- Always alias aggregate columns clearly.
- Order aggregated counts descending unless the user asks otherwise.

Question:
{question}
"""

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )

    return clean_sql(response.choices[0].message.content)


def summarize_results(question, sql, data, insights):
    sample_data = json.dumps(data[:2], indent=2, default=str)

    if len(sample_data) > 2000:
        sample_data = sample_data[:2000]

    prompt = f"""
You are a careful healthcare analytics assistant.

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
- Do not invent medicines, counts, uses, or side effects.
- If data is empty, say no matching records were found.
- If backend insights contain a top result, use that as the source of truth.
- If explaining medicine usage, explain it clearly using the use columns.
- Do not give medical advice or dosage instructions.
- Keep the response helpful, concise, and accurate.
- Avoid saying "consult a doctor" unless safety is directly relevant.
- Do not contradict the data.

Return format:
Direct Answer:
Key Insight:
"""

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )

    return response.choices[0].message.content.strip()