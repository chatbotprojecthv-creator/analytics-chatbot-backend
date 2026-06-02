from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from google.api_core.exceptions import BadRequest

from app.services.bigquery_service import (
    test_connection,
    get_schema,
    run_sql
)

from app.services.sql_validator import validate_sql

from app.services.groq_service import (
    generate_sql,
    summarize_results
)

from app.services.analytics_service import (
    generate_chart_data,
    generate_insights
)

app = FastAPI(title="NL to SQL Analytics Chatbot Backend")

CLIENT_TABLES = {
    "Hpharma": "pharma-ai-dashboard.Pharma_analytics.medicines",
    "Jpharma": "pharma-ai-dashboard.Pharma_analytics.Jpharma",
    "Vpharma": "pharma-ai-dashboard.Pharma_analytics.Vpharma"
}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def quote_col(col: str) -> str:
    return f"`{col}`" if " " in col else col


def build_similar_search_sql(question, schema_data, table_name):
    q = question.lower()

    column_names = [field["name"] for field in schema_data]

    searchable_cols = []

    for col in column_names:
        lower_col = col.lower()

        if (
            lower_col in [
                "name",
                "therapeutic class",
                "action class",
                "chemical class",
                "manufacturer",
                "composition"
            ]
            or lower_col.startswith("use")
            or lower_col.startswith("sideeffect")
            or lower_col.startswith("side_effect")
            or lower_col.startswith("substitute")
            or "composition" in lower_col
            or "manufacturer" in lower_col
        ):
            searchable_cols.append(col)

    keywords = []

    if "respiratory" in q or "lung" in q or "breathing" in q:
        keywords = ["respiratory", "respiratory tract", "lung", "breathing"]

    elif "pain" in q:
        keywords = ["pain", "analgesic", "pain analgesics"]

    elif "infection" in q or "infective" in q:
        keywords = ["infection", "infective", "anti infectives"]

    elif "heart" in q or "cardiac" in q:
        keywords = ["heart", "cardiac", "cardio"]

    elif "diabetes" in q or "diabetic" in q:
        keywords = ["diabetes", "diabetic", "anti diabetic"]

    else:
        words_to_remove = [
            "show", "list", "find", "give", "me", "all",
            "medicine", "medicines", "drug", "drugs",
            "tablet", "tablets", "capsule", "capsules",
            "used", "for", "with", "and", "the", "of",
            "what", "which", "class", "does", "belong", "to"
        ]

        cleaned = q

        for word in words_to_remove:
            cleaned = cleaned.replace(word, " ")

        keywords = [
            word.strip()
            for word in cleaned.split()
            if len(word.strip()) > 2
        ][:5]

    if not keywords:
        return None

    select_cols = []

    for preferred in [
        "name",
        "Therapeutic Class",
        "Action Class",
        "Chemical Class",
        "Habit Forming",
        "Manufacturer",
        "Composition"
    ]:
        if preferred in column_names:
            select_cols.append(quote_col(preferred))

    for col in column_names:
        lower_col = col.lower()

        if (
            lower_col.startswith("use")
            or "composition" in lower_col
            or "manufacturer" in lower_col
        ):
            quoted = quote_col(col)

            if quoted not in select_cols:
                select_cols.append(quoted)

    if not select_cols:
        select_cols = ["*"]

    where_parts = []

    for col in searchable_cols:
        for keyword in keywords:
            safe_keyword = keyword.replace("'", "\\'")
            where_parts.append(
                f"LOWER(CAST({quote_col(col)} AS STRING)) LIKE '%{safe_keyword}%'"
            )

    sql = f"""
SELECT
  {", ".join(select_cols)}
FROM `{table_name}`
WHERE
  {" OR ".join(where_parts)}
LIMIT 100;
"""

    return sql.strip()


@app.get("/")
def home():
    return {"message": "Backend is running"}


@app.get("/health")
def health():
    return test_connection(CLIENT_TABLES["Hpharma"])


@app.get("/clients")
def clients():
    return {
        "clients": list(CLIENT_TABLES.keys()),
        "tables": CLIENT_TABLES
    }


@app.get("/schema")
def schema(client: str = "Hpharma"):
    table_name = CLIENT_TABLES.get(client)

    if not table_name:
        raise HTTPException(status_code=400, detail="Invalid client")

    return get_schema(table_name)


@app.post("/ask")
def ask_question(payload: dict):
    client = payload.get("client")
    question = payload.get("question")

    if not client:
        raise HTTPException(status_code=400, detail="Client is required")

    if not question:
        raise HTTPException(status_code=400, detail="Question is required")

    table_name = CLIENT_TABLES.get(client)

    if not table_name:
        raise HTTPException(status_code=400, detail="Invalid client")

    print(f"Selected client: {client}")
    print(f"BigQuery table: {table_name}")

    normalized_question = question.lower()

    allowed_keywords = [
        "medicine", "medicines", "drug", "drugs",
        "tablet", "capsule", "syrup", "injection",
        "side effect", "side effects", "therapeutic",
        "class", "classes", "action class", "substitute",
        "habit forming", "chemical", "chemical class",
        "use", "uses", "used for",
        "nausea", "vomiting", "pain", "analgesic",
        "infection", "infective", "anti infectives",
        "cardiac", "heart", "cardio",
        "respiratory", "respiratory tract", "lung", "breathing",
        "diabetes", "diabetic", "anti diabetic",
        "manufacturer", "manufacturers",
        "composition", "compositions",
        "most side effects", "how many", "count", "total", "available",
        "amipar"
    ]

    dangerous_keywords = [
        "delete", "drop", "truncate", "update",
        "insert", "alter", "create", "merge"
    ]

    if any(keyword in normalized_question for keyword in dangerous_keywords):
        return {
            "question": question,
            "sql": None,
            "summary": "This request cannot be processed because it asks for an unsafe database operation.",
            "insights": {},
            "chart": None,
            "data": []
        }

    is_relevant = any(keyword in normalized_question for keyword in allowed_keywords)

    if not is_relevant:
        return {
            "question": question,
            "sql": None,
            "summary": (
                "I can answer questions related to the selected client's medicine dataset, including "
                "medicine uses, therapeutic classes, side effects, substitutes, "
                "habit-forming status, chemical class, action class, manufacturers, and compositions."
            ),
            "insights": {},
            "chart": None,
            "data": []
        }

    try:
        schema_data = get_schema(table_name)

        similar_search_terms = [
            "respiratory", "respiratory tract", "lung", "breathing",
            "pain", "infection", "infective", "heart", "cardiac",
            "diabetes", "diabetic", "used for", "medicines", "medicine",
            "drug", "drugs", "tablet", "capsule", "syrup",
            "amipar"
        ]

        if any(term in normalized_question for term in similar_search_terms):
            sql = build_similar_search_sql(
                question=question,
                schema_data=schema_data,
                table_name=table_name
            )

            if not sql:
                sql = generate_sql(
                    question=question,
                    schema=schema_data,
                    table_name=table_name
                )
        else:
            sql = generate_sql(
                question=question,
                schema=schema_data,
                table_name=table_name
            )

        if not validate_sql(sql, table_name):
            return {
                "question": question,
                "sql": sql,
                "summary": (
                    "I could not safely convert this question into a valid SQL query. "
                    "Please rephrase it using medicine-related terms."
                ),
                "insights": {},
                "chart": None,
                "data": []
            }

        data = run_sql(sql)

    except BadRequest as error:
        return {
            "question": question,
            "sql": sql if "sql" in locals() else None,
            "summary": "The generated SQL could not be executed. Please rephrase your question.",
            "error": str(error),
            "insights": {},
            "chart": None,
            "data": []
        }

    except Exception as error:
        return {
            "question": question,
            "sql": None,
            "summary": "Something went wrong while processing your question.",
            "error": str(error),
            "insights": {},
            "chart": None,
            "data": []
        }

    insights = generate_insights(data)

    medicine_detail_query = (
        "used for" in normalized_question
        or "what is" in normalized_question
        or "use of" in normalized_question
        or "belong to" in normalized_question
        or "medication class" in normalized_question
        or "medicines" in normalized_question
        or "medicine" in normalized_question
    )

    chart = None if medicine_detail_query else generate_chart_data(data)

    summary = summarize_results(
        question=question,
        sql=sql,
        data=data,
        insights=insights
    )

    return {
        "question": question,
        "sql": sql,
        "summary": summary,
        "insights": insights,
        "chart": chart,
        "data": data
    }