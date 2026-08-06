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
    validate_generated_sql_safety,
    guardrail_logs,
    run_guardrail_tests,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pharma-analytics-backend")

app = FastAPI(title="NL to SQL Analytics Chatbot Backend")

CLIENTS = ["All Clients", "Hpharma", "Jpharma", "Vpharma"]


class AskRequest(BaseModel):
    question: str
    client: Optional[str] = "All Clients"


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def normalize_client(client: Optional[str]) -> str:
    selected = (client or "All Clients").strip()

    if selected.lower() in {
        "",
        "all",
        "all clients",
        "medicines master",
    }:
        return "All Clients"

    for valid_client in CLIENTS:
        if selected.lower() == valid_client.lower():
            return valid_client

    return "All Clients"


def error_response(
    *,
    question: str,
    client: str,
    summary: str,
    guardrail_type: Optional[str] = None,
    error: Optional[str] = None,
):
    response = {
        "question": question,
        "client": client,
        "sql": None,
        "summary": summary,
        "guardrail_type": guardrail_type,
        "insights": {},
        "chart": None,
        "data": [],
    }

    if error:
        response["error"] = error

    return response


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

    guardrail_time = 0.0
    sql_generation_time = 0.0
    sql_validation_time = 0.0
    bigquery_time = 0.0
    summary_time = 0.0

    question = payload.question.strip()
    selected_client = normalize_client(payload.client)

    if not question:
        raise HTTPException(status_code=400, detail="Question is required")

    logger.info(
        "Ask request received | client=%s | question=%s",
        selected_client,
        question,
    )

    try:
        sql_start = time.time()

        sql = generate_sql(
            question=question,
            selected_client=selected_client,
        )

        sql_generation_time = round(time.time() - sql_start, 3)

        logger.info(
            "SQL generated | client=%s | duration_seconds=%s | sql_present=%s",
            selected_client,
            sql_generation_time,
            bool(sql),
        )

        if not sql:
            total_time = round(time.time() - request_start, 3)

            record_ai_pipeline_event(
                guardrail_time_ms=0,
                sql_generation_time_ms=sql_generation_time * 1000,
                sql_validation_time_ms=0,
                bigquery_time_ms=0,
                summary_generation_time_ms=0,
                total_request_time_ms=total_time * 1000,
                success=False,
                error_message="SQL generation returned an empty result",
                client=selected_client,
            )

            return error_response(
                question=question,
                client=selected_client,
                summary=(
                    "I could not convert this question into a valid analytics "
                    "query using the available warehouse schema. Please rephrase "
                    "the question or ask about medicines, clients, uses, side "
                    "effects, substitutes, or classifications."
                ),
                guardrail_type="invalid_generated_sql",
            )

        logger.info("=" * 80)
        logger.info("QUESTION:\n%s", question)
        logger.info("SELECTED CLIENT:\n%s", selected_client)
        logger.info("GENERATED SQL:\n%s", sql)

        validation_start = time.time()
        sql_valid = validate_sql(sql)
        sql_validation_time = round(time.time() - validation_start, 3)

        guardrail_start = time.time()
        safe_sql = validate_generated_sql_safety(sql)
        guardrail_time = round(time.time() - guardrail_start, 3)

        logger.info("validate_sql = %s", sql_valid)
        logger.info("validate_generated_sql_safety = %s", safe_sql)
        logger.info("=" * 80)

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
                error_message=(
                    "Generated SQL failed validation "
                    f"(validate_sql={sql_valid}, safety={safe_sql})"
                ),
                client=selected_client,
            )

            logger.warning(
                "SQL validation failed\n"
                "Question: %s\n"
                "Client: %s\n"
                "SQL:\n%s\n"
                "validate_sql=%s\n"
                "safe_sql=%s",
                question,
                selected_client,
                sql,
                sql_valid,
                safe_sql,
            )

            return error_response(
                question=question,
                client=selected_client,
                summary=(
                    "The generated query did not pass the read-only SQL "
                    "validation checks. Please rephrase the analytics question."
                ),
                guardrail_type="invalid_generated_sql",
            )

        bigquery_start = time.time()
        data = run_sql(sql)
        bigquery_time = round(time.time() - bigquery_start, 3)

        logger.info(
            "BigQuery query executed | client=%s | rows_returned=%s | "
            "duration_seconds=%s",
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
            client=selected_client,
        )

        logger.exception(
            "BigQuery BadRequest | client=%s | question=%s",
            selected_client,
            question,
        )

        return error_response(
            question=question,
            client=selected_client,
            summary=(
                "The generated analytics query reached BigQuery but could not "
                "be executed. Check the SQL and warehouse schema details."
            ),
            guardrail_type="query_execution_error",
            error=str(error),
        )

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
            client=selected_client,
        )

        logger.exception(
            "Unhandled backend error | client=%s | question=%s",
            selected_client,
            question,
        )

        return error_response(
            question=question,
            client=selected_client,
            summary="Something went wrong while processing your question.",
            guardrail_type="backend_error",
            error=str(error),
        )

    insights = generate_insights(data)
    chart = generate_chart_data(
        data=data,
        question=question,
    )

    summary_start = time.time()

    try:
        summary = summarize_results(
            question=question,
            sql=sql,
            data=data,
            insights=insights,
        )
    except Exception:
        logger.exception(
            "Summary generation failed | client=%s | question=%s",
            selected_client,
            question,
        )
        summary = (
            "The query executed successfully, but the natural-language "
            "summary could not be generated."
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
        client=selected_client,
        row_count=len(data),
        chart_type=chart.get("type") if chart else "",
        chart_reason=chart.get("reason") if chart else "",
    )

    logger.info(
        "Ask request completed | client=%s | rows_returned=%s | "
        "summary_time=%s | total_time=%s",
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