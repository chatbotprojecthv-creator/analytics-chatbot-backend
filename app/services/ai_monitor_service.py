import logging
from typing import Optional

logger = logging.getLogger(
    "pharma-analytics-backend"
)

try:
    import newrelic.agent as newrelic_agent
except ImportError:
    newrelic_agent = None


def record_custom_event(
    event_name: str,
    payload: dict,
) -> None:
    """
    Safely records a New Relic custom event.

    Monitoring failures must never interrupt the
    application request pipeline.
    """

    if newrelic_agent is None:
        logger.debug(
            "New Relic agent is unavailable; "
            "event '%s' was not recorded.",
            event_name,
        )
        return

    try:
        newrelic_agent.record_custom_event(
            event_name,
            payload,
        )
    except Exception as error:
        logger.warning(
            "Failed to record New Relic event "
            "'%s': %s",
            event_name,
            error,
        )


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
    Records an LLM request event.

    Event name:
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

    record_custom_event(
        "LLMRequest",
        payload,
    )


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


def record_ai_pipeline_event(
    guardrail_time_ms: float,
    sql_generation_time_ms: float,
    sql_validation_time_ms: float,
    bigquery_time_ms: float,
    summary_generation_time_ms: float,
    total_request_time_ms: float,
    success: bool = True,
    error_message: str = "",
    client: str = "",
    row_count: int = 0,
    chart_type: str = "",
    chart_reason: str = "",
) -> None:
    """
    Records timing and operational metadata for the
    complete AI analytics pipeline.

    Event name:
    AIPipelineEvent
    """

    payload = {
        "guardrail_time_ms": guardrail_time_ms,
        "sql_generation_time_ms": sql_generation_time_ms,
        "sql_validation_time_ms": sql_validation_time_ms,
        "bigquery_time_ms": bigquery_time_ms,
        "summary_generation_time_ms":
            summary_generation_time_ms,
        "total_request_time_ms":
            total_request_time_ms,
        "success": success,
        "error_message": error_message,
        "client": client,
        "row_count": row_count,
        "chart_type": chart_type,
        "chart_reason": chart_reason,
    }

    record_custom_event(
        "AIPipelineEvent",
        payload,
    )