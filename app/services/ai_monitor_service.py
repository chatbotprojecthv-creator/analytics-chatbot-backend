import logging
from typing import Optional

logger = logging.getLogger("pharma-analytics-backend")

try:
    import newrelic.agent
except Exception:
    newrelic = None


# ==========================================================
# Generic LLM Event
# ==========================================================

def record_llm_event(
    event_type: str,
    provider: str,
    model: str,
    prompt_length: int,
    response_length: int,
    latency_ms: float,
    success: bool,
    error_message: Optional[str] = None,
) -> None:
    """
    Records LLM observability events.

    Event Name:
    LLMRequest
    """

    payload = {
        "event_type": event_type,
        "provider": provider,
        "model": model,
        "prompt_length": prompt_length,
        "response_length": response_length,
        "latency_ms": latency_ms,
        "success": success,
        "error_message": error_message or "",
    }

    if newrelic:
        try:
            newrelic.agent.record_custom_event(
                "LLMRequest",
                payload,
            )
        except Exception as error:
            logger.warning(
                "Failed to record LLMRequest event: %s",
                error,
            )


# ==========================================================
# SQL Generation Event
# ==========================================================

def record_sql_generation(
    model: str,
    prompt_length: int,
    response_length: int,
    latency_ms: float,
    success: bool,
    error_message: Optional[str] = None,
) -> None:

    record_llm_event(
        event_type="sql_generation",
        provider="Groq",
        model=model,
        prompt_length=prompt_length,
        response_length=response_length,
        latency_ms=latency_ms,
        success=success,
        error_message=error_message,
    )


# ==========================================================
# Summary Generation Event
# ==========================================================

def record_summary_generation(
    model: str,
    prompt_length: int,
    response_length: int,
    latency_ms: float,
    success: bool,
    error_message: Optional[str] = None,
) -> None:

    record_llm_event(
        event_type="summary_generation",
        provider="Groq",
        model=model,
        prompt_length=prompt_length,
        response_length=response_length,
        latency_ms=latency_ms,
        success=success,
        error_message=error_message,
    )


# ==========================================================
# AI Pipeline Breakdown Event
# ==========================================================

def record_ai_pipeline_event(
    guardrail_time_ms: float,
    sql_generation_time_ms: float,
    sql_validation_time_ms: float,
    bigquery_time_ms: float,
    summary_generation_time_ms: float,
    total_request_time_ms: float,
    success: bool = True,
    error_message: str = "",
) -> None:
    """
    Records the complete AI pipeline timing.

    Event Name:
    AIPipelineEvent
    """

    payload = {
        "guardrail_time_ms": guardrail_time_ms,
        "sql_generation_time_ms": sql_generation_time_ms,
        "sql_validation_time_ms": sql_validation_time_ms,
        "bigquery_time_ms": bigquery_time_ms,
        "summary_generation_time_ms": summary_generation_time_ms,
        "total_request_time_ms": total_request_time_ms,
        "success": success,
        "error_message": error_message,
    }

    if newrelic:
        try:
            newrelic.agent.record_custom_event(
                "AIPipelineEvent",
                payload,
            )
        except Exception as error:
            logger.warning(
                "Failed to record AIPipelineEvent: %s",
                error,
            )