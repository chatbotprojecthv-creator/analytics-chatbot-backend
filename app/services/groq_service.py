import json
import re
import time
from typing import Any

from groq import Groq

from app.config import GROQ_API_KEY, WAREHOUSE_SCHEMA
from app.services.ai_monitor_service import (
    record_sql_generation,
    record_summary_generation,
)

groq_client = Groq(api_key=GROQ_API_KEY)

MODEL_NAME = "llama-3.1-8b-instant"

VALID_CLIENTS = ["Hpharma", "Jpharma", "Vpharma"]

# These phrases are used only to understand analytics intent.
# They are not a medical-safety guardrail.
INTENT_SYNONYMS = {
    "medicine_count": [
        "medicine count",
        "number of medicines",
        "how many medicines",
        "total medicines",
        "drug count",
        "product count",
    ],
    "medicine_records": [
        "medicine records",
        "medicine rows",
        "product records",
        "total rows",
    ],
    "unique_names": [
        "unique medicine names",
        "distinct medicine names",
        "different medicine names",
    ],
    "habit_forming": [
        "habit forming",
        "habit-forming",
        "addictive",
        "non habit forming",
        "non-habit-forming",
    ],
    "side_effects": [
        "side effect",
        "side effects",
        "adverse effect",
        "adverse effects",
    ],
    "uses": [
        "medicine use",
        "medicine uses",
        "used for",
        "use cases",
        "conditions treated",
        "indications",
    ],
    "substitutes": [
        "substitute",
        "substitutes",
        "alternative",
        "alternatives",
        "replacement",
        "replacements",
    ],
    "therapeutic_class": [
        "therapeutic class",
        "therapeutic classes",
    ],
    "chemical_class": [
        "chemical class",
        "chemical classes",
    ],
    "action_class": [
        "action class",
        "action classes",
        "mechanism class",
    ],
    "search": [
        "find medicine",
        "search medicine",
        "medicines containing",
        "medicines starting with",
        "medicine named",
    ],
    "comparison": [
        "compare",
        "comparison",
        "versus",
        " vs ",
        "difference between",
        "which client",
    ],
    "percentage": [
        "percentage",
        "percent",
        "share",
        "proportion",
        "distribution",
        "ratio",
    ],
    "ranking": [
        "top",
        "bottom",
        "most",
        "least",
        "highest",
        "lowest",
        "largest",
        "smallest",
    ],
}


def clean_sql(raw_sql: str) -> str:
    """
    Remove markdown and explanatory text from model-generated SQL.
    Return exactly one SQL statement ending with a semicolon.
    """
    sql = (raw_sql or "").strip()

    sql = re.sub(r"```(?:sql)?", "", sql, flags=re.IGNORECASE)
    sql = sql.replace("```", "")
    sql = re.sub(r"(?i)^sql\s*:\s*", "", sql).strip()

    # Keep only the first statement.
    if ";" in sql:
        sql = sql.split(";", 1)[0].strip()

    if not sql:
        return ""

    return f"{sql};"


def detect_explicit_clients(question: str) -> list[str]:
    """
    Return supported client names explicitly mentioned in the question.
    """
    if not question:
        return []

    detected: list[str] = []

    for client_name in VALID_CLIENTS:
        if re.search(
            rf"\b{re.escape(client_name)}\b",
            question,
            flags=re.IGNORECASE,
        ):
            detected.append(client_name)

    return detected


def normalize_selected_client(selected_client: str | None) -> str:
    """
    Normalize frontend client values.
    """
    selected = (selected_client or "All Clients").strip()

    if selected.lower() in {
        "",
        "all",
        "all clients",
        "medicines master",
    }:
        return "All Clients"

    for valid_client in VALID_CLIENTS:
        if selected.lower() == valid_client.lower():
            return valid_client

    return "All Clients"


def resolve_client_scope(
    question: str,
    selected_client: str | None,
) -> dict[str, Any]:
    """
    Explicit clients in the question override the dropdown.
    """
    explicit_clients = detect_explicit_clients(question)

    if explicit_clients:
        return {
            "source": "question",
            "clients": explicit_clients,
            "apply_filter": True,
        }

    selected = normalize_selected_client(selected_client)

    if selected == "All Clients":
        return {
            "source": "dropdown",
            "clients": [],
            "apply_filter": False,
        }

    return {
        "source": "dropdown",
        "clients": [selected],
        "apply_filter": True,
    }


def detect_intents(question: str) -> list[str]:
    """
    Detect likely analytics intents for prompt guidance.
    The LLM still interprets the final meaning.
    """
    normalized = f" {question.lower().strip()} "
    detected: list[str] = []

    for intent, phrases in INTENT_SYNONYMS.items():
        if any(phrase in normalized for phrase in phrases):
            detected.append(intent)

    return detected or ["general_pharma_analytics"]


def extract_requested_limit(
    question: str,
    default: int = 10,
    maximum: int = 100,
) -> int:
    """
    Extract Top N / Bottom N safely.
    """
    patterns = [
        r"\btop\s+(\d+)\b",
        r"\bbottom\s+(\d+)\b",
        r"\bfirst\s+(\d+)\b",
        r"\blimit\s+(\d+)\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, question, flags=re.IGNORECASE)
        if match:
            return max(1, min(int(match.group(1)), maximum))

    return default


def build_client_condition(
    client_scope: dict[str, Any],
    alias: str = "c",
) -> str:
    """
    Build a client predicate without WHERE or AND.
    """
    if not client_scope["apply_filter"]:
        return ""

    clients = client_scope["clients"]

    if len(clients) == 1:
        return f"{alias}.client_name = '{clients[0]}'"

    values = ", ".join(f"'{name}'" for name in clients)
    return f"{alias}.client_name IN ({values})"


def build_client_instruction(
    client_scope: dict[str, Any],
) -> str:
    """
    Convert resolved client scope to explicit prompt instructions.
    """
    clients = client_scope["clients"]

    if not client_scope["apply_filter"]:
        return """
CLIENT SCOPE

- Use all clients.
- Do not add a client_name filter.
- "All Clients" is a UI option, not a row in the clients table.
- Never generate c.client_name = 'All Clients'.
"""

    if len(clients) == 1:
        return f"""
CLIENT SCOPE

- Use exactly this client: {clients[0]}
- When a clients join is present, filter with:
  c.client_name = '{clients[0]}'
"""

    values = ", ".join(f"'{name}'" for name in clients)

    return f"""
CLIENT SCOPE

- Compare exactly these clients: {", ".join(clients)}
- Filter with:
  c.client_name IN ({values})
- These explicitly mentioned clients override the dropdown.
- Group by c.client_name when the result compares clients.
"""


def build_known_query(
    question: str,
    client_scope: dict[str, Any],
) -> str | None:
    """
    Deterministic SQL for high-frequency questions whose schema is known.

    Other supported questions go through the schema-aware LLM prompt.
    """
    normalized = re.sub(
        r"[^a-z0-9\s-]",
        " ",
        question.lower(),
    )
    normalized = re.sub(r"\s+", " ", normalized).strip()

    client_condition = build_client_condition(client_scope, alias="c")

    # 1. Top / most common side effects.
    if (
        "side effect" in normalized
        and (
            "top" in normalized
            or "most common" in normalized
            or "affect the most" in normalized
        )
        and "compare" not in normalized
        and " by client" not in normalized
    ):
        limit = extract_requested_limit(question)

        joins = """
FROM `pharma-ai-dashboard.Pharma_Warehouse.medicine_side_effects` AS mse
JOIN `pharma-ai-dashboard.Pharma_Warehouse.side_effects` AS se
  ON mse.side_effect_id = se.side_effect_id"""

        where_clause = ""

        if client_condition:
            joins += """
JOIN `pharma-ai-dashboard.Pharma_Warehouse.medicines_master` AS m
  ON mse.medicine_id = m.medicine_id
JOIN `pharma-ai-dashboard.Pharma_Warehouse.clients` AS c
  ON m.client_id = c.client_id"""
            where_clause = f"\nWHERE {client_condition}"

        return f"""SELECT
  se.side_effect_name,
  COUNT(DISTINCT mse.medicine_id) AS affected_medicines
{joins}{where_clause}
GROUP BY se.side_effect_name
ORDER BY affected_medicines DESC
LIMIT {limit};"""

    # 2. Habit-forming count or comparison by client.
    if (
        "habit forming" in normalized
        or "habit-forming" in normalized
        or "addictive" in normalized
    ) and (
        "compare" in normalized
        or " by client" in normalized
        or len(client_scope["clients"]) > 1
        or "which client" in normalized
    ):
        conditions: list[str] = []

        if client_condition:
            conditions.append(client_condition)

        is_non_habit = (
            "non habit forming" in normalized
            or "non-habit-forming" in normalized
            or "not habit forming" in normalized
        )

        if is_non_habit:
            conditions.append(
                "LOWER(CAST(m.habit_forming AS STRING)) "
                "IN ('false', 'no', '0')"
            )
            metric_alias = "non_habit_forming_medicine_count"
        else:
            conditions.append(
                "LOWER(CAST(m.habit_forming AS STRING)) "
                "IN ('true', 'yes', '1')"
            )
            metric_alias = "habit_forming_medicine_count"

        where_clause = "\n  AND ".join(conditions)

        return f"""SELECT
  c.client_name,
  COUNT(
    DISTINCT TO_JSON_STRING(
      STRUCT(
        LOWER(TRIM(m.medicine_name)) AS medicine_name,
        m.habit_forming AS habit_forming,
        m.therapeutic_class_id AS therapeutic_class_id,
        m.chemical_class_id AS chemical_class_id,
        m.action_class_id AS action_class_id
      )
    )
  ) AS {metric_alias}
FROM `pharma-ai-dashboard.Pharma_Warehouse.medicines_master` AS m
JOIN `pharma-ai-dashboard.Pharma_Warehouse.clients` AS c
  ON m.client_id = c.client_id
WHERE {where_clause}
GROUP BY c.client_name
ORDER BY {metric_alias} DESC;"""

    # 3. Medicine count by client / client comparison.
    medicine_count_phrases = [
        "medicine count",
        "number of medicines",
        "how many medicines",
        "total medicines",
    ]

    if any(phrase in normalized for phrase in medicine_count_phrases) and (
        " by client" in normalized
        or "compare" in normalized
        or "which client" in normalized
        or len(client_scope["clients"]) > 1
    ):
        where_clause = (
            f"\nWHERE {client_condition}"
            if client_condition
            else ""
        )

        return f"""SELECT
  c.client_name,
  COUNT(
    DISTINCT TO_JSON_STRING(
      STRUCT(
        LOWER(TRIM(m.medicine_name)) AS medicine_name,
        m.habit_forming AS habit_forming,
        m.therapeutic_class_id AS therapeutic_class_id,
        m.chemical_class_id AS chemical_class_id,
        m.action_class_id AS action_class_id
      )
    )
  ) AS medicine_count
FROM `pharma-ai-dashboard.Pharma_Warehouse.medicines_master` AS m
JOIN `pharma-ai-dashboard.Pharma_Warehouse.clients` AS c
  ON m.client_id = c.client_id{where_clause}
GROUP BY c.client_name
ORDER BY medicine_count DESC;"""

    # 4. Combined medicine metrics by client.
    # This must come before the single-metric unique-name template.
    combined_metric_terms = [
        "medicine records",
        "unique medicine names",
        "unique business medicines",
    ]

    if (
        "client" in normalized
        and sum(term in normalized for term in combined_metric_terms) >= 2
    ):
        where_clause = (
            f"\nWHERE {client_condition}"
            if client_condition
            else ""
        )

        return f"""SELECT
  c.client_name,
  COUNT(DISTINCT m.medicine_id) AS medicine_records,
  COUNT(
    DISTINCT LOWER(TRIM(m.medicine_name))
  ) AS unique_medicine_names,
  COUNT(
    DISTINCT TO_JSON_STRING(
      STRUCT(
        LOWER(TRIM(m.medicine_name)) AS medicine_name,
        m.habit_forming AS habit_forming,
        m.therapeutic_class_id AS therapeutic_class_id,
        m.chemical_class_id AS chemical_class_id,
        m.action_class_id AS action_class_id
      )
    )
  ) AS unique_business_medicines
FROM `pharma-ai-dashboard.Pharma_Warehouse.medicines_master` AS m
JOIN `pharma-ai-dashboard.Pharma_Warehouse.clients` AS c
  ON m.client_id = c.client_id{where_clause}
GROUP BY c.client_name
ORDER BY medicine_records DESC;"""

    # 5. Top action classes.
    # Use action_class_id directly because it is guaranteed by the known
    # medicines_master schema. This avoids undefined lookup aliases.
    if (
        "action class" in normalized
        and (
            "top" in normalized
            or "most common" in normalized
            or "highest" in normalized
        )
    ):
        limit = extract_requested_limit(question)
        conditions: list[str] = []

        if client_condition:
            conditions.append(client_condition)

        # "Top action classes" normally means classified values only.
        conditions.append("m.action_class_id IS NOT NULL")

        where_clause = "\n  AND ".join(conditions)

        return f"""SELECT
  CAST(m.action_class_id AS STRING) AS action_class,
  COUNT(DISTINCT m.medicine_id) AS medicine_count
FROM `pharma-ai-dashboard.Pharma_Warehouse.medicines_master` AS m
JOIN `pharma-ai-dashboard.Pharma_Warehouse.clients` AS c
  ON m.client_id = c.client_id
WHERE {where_clause}
GROUP BY action_class
ORDER BY medicine_count DESC
LIMIT {limit};"""

    # 6. Unique medicine names by client.
    if (
        "unique medicine names" in normalized
        or "distinct medicine names" in normalized
    ) and (
        " by client" in normalized
        or "compare" in normalized
        or len(client_scope["clients"]) > 1
    ):
        where_clause = (
            f"\nWHERE {client_condition}"
            if client_condition
            else ""
        )

        return f"""SELECT
  c.client_name,
  COUNT(DISTINCT LOWER(TRIM(m.medicine_name))) AS unique_medicine_names
FROM `pharma-ai-dashboard.Pharma_Warehouse.medicines_master` AS m
JOIN `pharma-ai-dashboard.Pharma_Warehouse.clients` AS c
  ON m.client_id = c.client_id{where_clause}
GROUP BY c.client_name
ORDER BY unique_medicine_names DESC;"""

    # 7. Medicine records by client.
    if (
        "medicine records" in normalized
        or "product records" in normalized
        or "medicine rows" in normalized
    ) and (
        " by client" in normalized
        or "compare" in normalized
        or len(client_scope["clients"]) > 1
    ):
        where_clause = (
            f"\nWHERE {client_condition}"
            if client_condition
            else ""
        )

        return f"""SELECT
  c.client_name,
  COUNT(DISTINCT m.medicine_id) AS medicine_record_count
FROM `pharma-ai-dashboard.Pharma_Warehouse.medicines_master` AS m
JOIN `pharma-ai-dashboard.Pharma_Warehouse.clients` AS c
  ON m.client_id = c.client_id{where_clause}
GROUP BY c.client_name
ORDER BY medicine_record_count DESC;"""

    return None


def build_generation_prompt(
    question: str,
    client_scope: dict[str, Any],
    detected_intents: list[str],
) -> str:
    """
    Build the schema-aware generation prompt.
    """
    client_instruction = build_client_instruction(client_scope)
    intent_json = json.dumps(detected_intents, indent=2)

    return f"""
You are an expert BigQuery SQL generator for a pharma analytics warehouse.

Use only the schema supplied below. The schema is the source of truth for
table names, column names, and join keys.

WAREHOUSE SCHEMA

{WAREHOUSE_SCHEMA}

DETECTED QUESTION INTENTS

{intent_json}

{client_instruction}

CORE OUTPUT RULES

- Return SQL only.
- Do not return markdown, comments, JSON, prose, or explanations.
- Generate exactly one BigQuery Standard SQL statement.
- The statement must begin with SELECT or WITH.
- Generate a read-only analytics query.
- Use fully qualified table names enclosed in backticks.
- Never generate INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, MERGE,
  CREATE, REPLACE, GRANT, REVOKE, CALL, EXECUTE, EXPORT, or LOAD.
- Never invent a table, column, value, or relationship.
- Every alias referenced in SELECT, WHERE, JOIN, GROUP BY, HAVING,
  QUALIFY, or ORDER BY must be defined in FROM or JOIN.
- Every selected non-aggregate column must appear in GROUP BY.
- Use SAFE_DIVIDE for ratios and percentages.
- Use SAFE_CAST only when schema types require it.
- Use LIMIT 100 for detail/list queries unless another limit is requested.
- For "top", "bottom", "most", or "least" with no number, use LIMIT 10.
- Do not apply LIMIT to a single aggregate row unless requested.

CLIENT INTERPRETATION

Valid client values:
- Hpharma
- Jpharma
- Vpharma

Rules:
- Explicit client names in the question override the dropdown.
- "All Clients" means no client filter.
- Never use "All Clients" or "Medicines Master" as client_name values.
- For client filtering or grouping, join medicines_master to clients using
  the join supported by the schema.
- When comparing clients, return c.client_name and group by c.client_name.

MEDICINE COUNT SEMANTICS

The medicines_master table has unique medicine_id values, but medicine names
can repeat.

Interpret metrics exactly:

1. "medicine records", "product records", "rows"
   -> COUNT(DISTINCT m.medicine_id)

2. "unique medicine names", "distinct medicine names"
   -> COUNT(DISTINCT LOWER(TRIM(m.medicine_name)))

3. "unique medicines", general "medicine count", or "number of medicines"
   -> Count distinct business variants:

   COUNT(
     DISTINCT TO_JSON_STRING(
       STRUCT(
         LOWER(TRIM(m.medicine_name)) AS medicine_name,
         m.habit_forming AS habit_forming,
         m.therapeutic_class_id AS therapeutic_class_id,
         m.chemical_class_id AS chemical_class_id,
         m.action_class_id AS action_class_id
       )
     )
   )

4. Do not use COUNT(*) for medicine counts unless table rows are explicitly
   requested.

5. After one-to-many relationship joins, use COUNT(DISTINCT medicine_id)
   when counting affected medicine records.

MISSING CLASSIFICATION RULES

- therapeutic_class_id, chemical_class_id, and action_class_id may
  legitimately be NULL.
- Never invent, infer, or fabricate a missing classification.
- When listing or grouping classification data, preserve unclassified
  medicines.
- Use LEFT JOIN instead of INNER JOIN when a lookup join could remove
  medicines with missing class metadata.
- Represent a missing class as 'Not Available' with COALESCE or CASE.
- Exclude NULL classifications only when the user explicitly asks for
  classified medicines, known classes, mapped classes, or available classes.
- For class distributions, include a 'Not Available' category unless the
  user explicitly asks to exclude missing classifications.
- When calculating percentages, keep the denominator consistent:
  * "percentage of all medicines" includes unclassified medicines.
  * "percentage among classified medicines" excludes NULL class values.
- When grouping directly by an ID, use:
  COALESCE(CAST(m.<class_column> AS STRING), 'Not Available')
- When grouping by a lookup name, use:
  COALESCE(<lookup_alias>.<name_column>, 'Not Available')
- Do not use WHERE <class_column> IS NOT NULL unless the user's wording
  explicitly requires classified-only results.

QUESTION FAMILIES TO SUPPORT

A. MEDICINE COUNTS
Examples:
- How many medicines does each client have?
- Compare medicine counts for Hpharma and Vpharma.
- Which client has the most medicines?
- Count unique medicine names by client.
- Show medicine records for Jpharma.

B. HABIT-FORMING ANALYSIS
Examples:
- Compare habit-forming medicines by client.
- Which client has the most addictive medicines?
- Show non-habit-forming medicines.
- What percentage of each client's medicines are habit forming?

Interpret:
- habit forming / habit-forming / addictive:
  LOWER(CAST(m.habit_forming AS STRING)) IN ('true', 'yes', '1')
- non-habit-forming:
  LOWER(CAST(m.habit_forming AS STRING)) IN ('false', 'no', '0')

C. SIDE EFFECTS
Examples:
- Show top 10 side effects.
- Which side effects affect the most medicines?
- Compare side effects across clients.
- Show medicines associated with nausea.
- List side effects for a named medicine.

Use only the side-effect tables and columns shown in the schema.
For affected medicine counts, count distinct medicine IDs.

D. MEDICINE USES
Examples:
- Show the most common medicine uses.
- Which use has the most medicines?
- Compare uses by client.
- Show medicines used for bacterial infections.
- List uses for a named medicine.

Use the medicines, medicine-use relationship, and uses tables from the schema.
Count distinct medicine IDs after the relationship join.

E. SUBSTITUTES
Examples:
- Show substitutes for a named medicine.
- Which medicines have the most substitutes?
- Compare substitute counts by client.
- List medicines without substitutes.

Use only the substitute relationship and lookup columns in the schema.
"Alternative" or "replacement" means substitute only in an analytics context.

F. THERAPEUTIC CLASSES
Examples:
- Count medicines by therapeutic class.
- Show top therapeutic classes.
- Compare therapeutic classes by client.
- List medicines in a therapeutic class.

Use a lookup table only if it exists in the supplied schema.
Otherwise group by the class ID.
Preserve NULL classifications and label them 'Not Available' unless the
user explicitly asks for classified-only results.
Never invent a class name.

G. CHEMICAL CLASSES
Examples:
- Show top chemical classes.
- Count medicines by chemical class.
- Compare chemical classes across clients.
- List medicines in a chemical class.

Join using only the schema-supported key and type conversion.
Use LEFT JOIN when a lookup table is required.
Preserve NULL classifications as 'Not Available' unless explicitly excluded.

H. ACTION CLASSES
Examples:
- Show top action classes.
- Count medicines by action class.
- Compare action classes across clients.
- List medicines in an action class.

Join using only the schema-supported key and type conversion.
Use LEFT JOIN when a lookup table is required.
Preserve NULL classifications as 'Not Available' unless explicitly excluded.

I. MEDICINE SEARCH AND DETAILS
Examples:
- Find medicines containing "azi".
- List medicines starting with "para".
- Show all variants of a named medicine.
- Show medicine name, client, habit-forming status, and classes.

Use case-insensitive matching.
Use DISTINCT when joins could duplicate detail rows.

J. RANKINGS
Examples:
- Top 5 uses.
- Bottom 10 classes.
- Most common side effects.
- Medicines with the most substitutes.

Use the requested sort direction and requested limit.

K. PERCENTAGES AND DISTRIBUTIONS
Examples:
- Percentage of habit-forming medicines by client.
- Share of medicines belonging to each client.
- Distribution of medicines by therapeutic class.
- Habit-forming versus non-habit-forming percentages.

Use SAFE_DIVIDE and multiply by 100 for percentage output.
Use an alias ending with _percentage.

L. MULTI-FILTER QUESTIONS
Examples:
- Habit-forming medicines in Jpharma associated with nausea.
- Top uses for non-habit-forming medicines in Hpharma.
- Vpharma medicines with substitutes and a given side effect.
- Compare substitute counts for habit-forming medicines.

Combine independent filters with AND.
Use every required relationship table.
Prevent duplicate inflation with DISTINCT.

M. OVERLAP AND COMMON MEDICINES
Examples:
- Medicines common to Jpharma and Vpharma.
- How many medicine names overlap between two clients?
- Medicines unique to Hpharma.
- Compare shared medicine names across clients.

For name overlap:
- Normalize with LOWER(TRIM(medicine_name)).
- Use self-joins, conditional aggregation, or set operations.
- Use medicine name semantics unless business variants are explicitly asked.

N. DATA QUALITY
Examples:
- Find duplicate medicine names.
- Show medicine names with different attributes.
- Count missing class IDs.
- Find medicines without uses, side effects, or substitutes.
- Show unmapped relationship records.

Use LEFT JOIN and NULL checks where appropriate.
Do not treat repeated medicine names as duplicate IDs.
Distinguish:
- repeated name
- repeated identical business variant
- same name with different attributes

O. COMBINED OUTPUTS
Examples:
- Show each client with medicine count and habit-forming percentage.
- Compare clients by medicines, side effects, and uses.
- Show a class with its medicine count and client distribution.

Use CTEs to compute independent aggregates before joining them.
Do not directly join multiple one-to-many relationship tables and count rows,
because that creates multiplicative duplication.

DETAIL VERSUS AGGREGATE

Aggregate intent words:
- count, how many, total, average, percentage, share, distribution,
  compare, top, bottom, most, least

For aggregate questions:
- Return only grouping columns and calculated metrics.
- Group correctly.
- Use clear metric aliases.

Detail intent words:
- list, show medicines, find, search, which medicines, names

For detail questions:
- Return relevant descriptive columns.
- Use DISTINCT where required.
- Apply LIMIT 100 unless another limit is requested.

FINAL SELF-CHECK BEFORE RETURNING SQL

Silently verify:
1. Every table and column exists in the supplied schema.
2. Every alias is defined.
3. All join keys are valid.
4. Client scope is followed exactly.
5. "All Clients" is not used as a database value.
6. The count semantics match the user's wording.
7. One-to-many joins do not inflate counts.
8. GROUP BY is valid.
9. The query is read-only.
10. The result directly answers the question.
11. Missing classifications are preserved unless the user asked to exclude them.
12. LEFT JOIN is used where an INNER JOIN would remove unclassified medicines.
13. NULL class values are labeled 'Not Available' in class listings or distributions.

USER QUESTION

{question}
"""


def generate_sql(
    question: str,
    *,
    selected_client: str | None = "All Clients",
    schema: Any = None,
    table_name: Any = None,
) -> str:
    """
    Generate one safe, schema-aware, read-only BigQuery query.

    Correct caller:

        generate_sql(
            question=request.question,
            selected_client=request.client,
        )
    """
    if not question or not question.strip():
        return ""

    start_time = time.time()

    client_scope = resolve_client_scope(
        question=question,
        selected_client=selected_client,
    )
    detected_intents = detect_intents(question)

    # Deterministic templates for common, high-confidence cases.
    deterministic_sql = build_known_query(
        question=question,
        client_scope=client_scope,
    )

    if deterministic_sql:
        latency_ms = round((time.time() - start_time) * 1000, 2)

        record_sql_generation(
            model="deterministic-template",
            prompt_length=len(question),
            response_length=len(deterministic_sql),
            latency_ms=latency_ms,
            success=True,
        )

        print("\n========== SQL GENERATION ==========")
        print("Source: deterministic template")
        print("Question:", question)
        print("Selected client:", selected_client)
        print("Resolved scope:", client_scope)
        print("Detected intents:", detected_intents)
        print("SQL:")
        print(deterministic_sql)
        print("====================================\n")

        return deterministic_sql

    prompt = build_generation_prompt(
        question=question,
        client_scope=client_scope,
        detected_intents=detected_intents,
    )

    try:
        response = groq_client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You generate one valid, read-only BigQuery SQL query "
                        "using only the supplied schema. Return SQL only."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=0,
        )

        raw_sql = response.choices[0].message.content or ""
        cleaned_sql = clean_sql(raw_sql)

        latency_ms = round((time.time() - start_time) * 1000, 2)

        record_sql_generation(
            model=MODEL_NAME,
            prompt_length=len(prompt),
            response_length=len(cleaned_sql),
            latency_ms=latency_ms,
            success=bool(cleaned_sql),
        )

        print("\n========== SQL GENERATION ==========")
        print("Source: Groq")
        print("Question:", question)
        print("Selected client:", selected_client)
        print("Resolved scope:", client_scope)
        print("Detected intents:", detected_intents)
        print("SQL:")
        print(cleaned_sql)
        print("====================================\n")

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

        raise


def summarize_results(
    question: str,
    sql: str,
    data: list,
    insights: dict,
) -> str:
    """
    Summarize only the executed query result and backend insights.
    """
    if not data:
        return (
            "Direct Answer:\n"
            "No matching records were found.\n\n"
            "Key Insight:\n"
            "The executed query returned an empty result."
        )

    result_sample = data[:20]

    sample_data = json.dumps(
        result_sample,
        indent=2,
        default=str,
    )

    if len(sample_data) > 6000:
        sample_data = sample_data[:6000]

    prompt = f"""
You are a careful pharma analytics assistant.

USER QUESTION
{question}

EXECUTED SQL
{sql}

TOTAL RESULT ROWS
{len(data)}

BACKEND INSIGHTS
{json.dumps(insights, indent=2, default=str)}

BIGQUERY RESULT SAMPLE
{sample_data}

RULES

- Use only the executed result and backend insights.
- Never invent clients, medicines, counts, percentages, classes, uses,
  side effects, substitutes, or relationships.
- Preserve the exact meaning of each SQL metric alias.
- Distinguish medicine records, unique names, and business variants.
- Do not claim causation from association data.
- For comparison results, mention only visible clients or categories.
- Do not provide medical recommendations, diagnoses, dosages, prescriptions,
  or treatment advice.
- Keep the response concise.
- Do not add a markdown table.

Return exactly:

Direct Answer:
<answer>

Key Insight:
<insight>
"""

    start_time = time.time()

    try:
        response = groq_client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Summarize only the supplied analytics result. "
                        "Do not invent facts."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=0,
        )

        summary = (
            response.choices[0].message.content
            or ""
        ).strip()

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

        raise