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
        "class", "action class", "substitute",
        "habit forming", "chemical", "use", "uses",
        "used for", "nausea", "vomiting", "pain",
        "infection", "cardiac", "respiratory",
        "anti infectives", "most side effects",
        "how many", "count", "total", "available"
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
                "habit-forming status, chemical class, and action class."
            ),
            "insights": {},
            "chart": None,
            "data": []
        }

    try:
        schema_data = get_schema(table_name)

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