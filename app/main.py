import logging
import time
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from google.api_core.exceptions import BadRequest
from pydantic import BaseModel

from app.config import TABLES
from app.services.bigquery_service import test_connection, get_schema, run_sql
from app.services.sql_validator import validate_sql
from app.services.groq_service import generate_sql, summarize_results
from app.services.analytics_service import generate_chart_data, generate_insights
from app.services.ai_monitor_service import record_ai_pipeline_event
from app.services.guardrails import (
    validate_question_guardrails,
    validate_generated_sql_safety,
    blocked_response,
    guardrail_logs,
    run_guardrail_tests,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pharma-analytics-backend")

app = FastAPI(title="NL to SQL Analytics Chatbot Backend")

CLIENTS = ["Medicines Master", "Jpharma", "Vpharma"]


class AskRequest(BaseModel):
    question: str
    client: Optional[str] = "Medicines Master"


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def home():
    logger.info("Health check: root endpoint called")
    return {"message": "Backend is running"}


@app.get("/health")
def health():
    logger.info("Health check: BigQuery connection test started")
    return test_connection(TABLES["medicines_master"])


@app.get("/clients")
def clients():
    logger.info("Clients endpoint called")
    return {"clients": CLIENTS}


@app.get("/schema")
def schema():
    logger.info("Schema endpoint called")
    return {
        "tables": TABLES,
        "main_table_schema": get_schema(TABLES["medicines_master"]),
    }


@app.get("/guardrail-logs")
def get_guardrail_logs():
    logger.info("Guardrail logs endpoint called")
    return {"logs": guardrail_logs}


@app.get("/guardrail-test")
def guardrail_test():
    logger.info("Guardrail test endpoint called")
    return {"tests": run_guardrail_tests()}


@app.post("/ask")
def ask_question(payload: AskRequest):
    request_start = time.time()

    guardrail_time = 0
    sql_generation_time = 0
    sql_validation_time = 0
    bigquery_time = 0
    summary_time = 0

    question = payload.question.strip()
    selected_client = payload.client or "Medicines Master"

    if not question:
        raise HTTPException(status_code=400, detail="Question is required")

    logger.info(
        "Ask request received | client=%s | question=%s",
        selected_client,
        question,
    )

    guardrail_start = time.time()
    guardrail_result = validate_question_guardrails(question, selected_client)
    guardrail_time = round(time.time() - guardrail_start, 3)

    if guardrail_result:
        total_time = round(time.time() - request_start, 3)

        record_ai_pipeline_event(
            guardrail_time_ms=guardrail_time * 1000,
            sql_generation_time_ms=0,
            sql_validation_time_ms=0,
            bigquery_time_ms=0,
            summary_generation_time_ms=0,
            total_request_time_ms=total_time * 1000,
            success=False,
            error_message=f"Blocked by guardrail: {guardrail_result.get('guardrail_type')}",
        )

        logger.warning(
            "Guardrail blocked request | type=%s | client=%s | question=%s",
            guardrail_result.get("guardrail_type"),
            selected_client,
            question,
        )
        return guardrail_result

    try:
        final_question = question

        if selected_client and selected_client != "Medicines Master":
            final_question = f"{question}. Filter results for client {selected_client}."

        sql_start = time.time()

        sql = generate_sql(
            question=final_question,
            schema=None,
            table_name=None,
        )

        sql_generation_time = round(time.time() - sql_start, 3)

        logger.info(
            "SQL generated | client=%s | duration_seconds=%s",
            selected_client,
            sql_generation_time,
        )

        validation_start = time.time()

        sql_valid = validate_sql(sql)
        safe_sql = validate_generated_sql_safety(sql)

        sql_validation_time = round(time.time() - validation_start, 3)

        if not sql_valid or not safe_sql:
            total_time = round(time.time() - request_start, 3)

            record_ai_pipeline_event(
                guardrail_time_ms=guardrail_time * 1000,
                sql_generation_time_ms=sql_generation_time * 1000,
                sql_validation_time_ms=sql_validation_time * 1000,
                bigquery_time_ms=0,
                summary_generation_time_ms=0,
                total_request_time_ms=total_time * 1000,
                success=False,
                error_message="Generated SQL failed validation",
            )

            logger.warning(
                "SQL validation failed | client=%s | question=%s",
                selected_client,
                question,
            )

            return blocked_response(
                question=question,
                client=selected_client,
                summary=(
                    "I could not safely convert this question into a valid read-only analytics query.\n\n"
                    "Try asking about medicine counts, side effects, uses, client comparisons, "
                    "or habit-forming medicines."
                ),
                guardrail_type="unsafe_request",
                reason="Generated SQL failed validation",
            )

        bigquery_start = time.time()
        data = run_sql(sql)
        bigquery_time = round(time.time() - bigquery_start, 3)

        logger.info(
            "BigQuery query executed | client=%s | rows_returned=%s | duration_seconds=%s",
            selected_client,
            len(data),
            bigquery_time,
        )

    except BadRequest as error:
        total_time = round(time.time() - request_start, 3)

        record_ai_pipeline_event(
            guardrail_time_ms=guardrail_time * 1000,
            sql_generation_time_ms=sql_generation_time * 1000,
            sql_validation_time_ms=sql_validation_time * 1000,
            bigquery_time_ms=bigquery_time * 1000,
            summary_generation_time_ms=summary_time * 1000,
            total_request_time_ms=total_time * 1000,
            success=False,
            error_message=str(error),
        )

        logger.exception(
            "BigQuery BadRequest | client=%s | question=%s",
            selected_client,
            question,
        )

        return {
            "question": question,
            "client": selected_client,
            "sql": None,
            "summary": "The analytics query could not be executed. Please rephrase your question.",
            "guardrail_type": None,
            "error": str(error),
            "insights": {},
            "chart": None,
            "data": [],
        }

    except Exception as error:
        total_time = round(time.time() - request_start, 3)

        record_ai_pipeline_event(
            guardrail_time_ms=guardrail_time * 1000,
            sql_generation_time_ms=sql_generation_time * 1000,
            sql_validation_time_ms=sql_validation_time * 1000,
            bigquery_time_ms=bigquery_time * 1000,
            summary_generation_time_ms=summary_time * 1000,
            total_request_time_ms=total_time * 1000,
            success=False,
            error_message=str(error),
        )

        logger.exception(
            "Unhandled backend error | client=%s | question=%s",
            selected_client,
            question,
        )

        return {
            "question": question,
            "client": selected_client,
            "sql": None,
            "summary": "Something went wrong while processing your question.",
            "guardrail_type": None,
            "error": str(error),
            "insights": {},
            "chart": None,
            "data": [],
        }

    insights = generate_insights(data)
    chart = generate_chart_data(data)

    summary_start = time.time()

    summary = summarize_results(
        question=question,
        sql=sql,
        data=data,
        insights=insights,
    )

    summary_time = round(time.time() - summary_start, 3)
    total_time = round(time.time() - request_start, 3)

    record_ai_pipeline_event(
        guardrail_time_ms=guardrail_time * 1000,
        sql_generation_time_ms=sql_generation_time * 1000,
        sql_validation_time_ms=sql_validation_time * 1000,
        bigquery_time_ms=bigquery_time * 1000,
        summary_generation_time_ms=summary_time * 1000,
        total_request_time_ms=total_time * 1000,
        success=True,
        error_message="",
    )

    logger.info(
        "Ask request completed | client=%s | rows_returned=%s | summary_time=%s | total_time=%s",
        selected_client,
        len(data),
        summary_time,
        total_time,
    )

    return {
        "question": question,
        "client": selected_client,
        "sql": sql,
        "summary": summary,
        "guardrail_type": None,
        "insights": insights,
        "chart": chart,
        "data": data,
    }