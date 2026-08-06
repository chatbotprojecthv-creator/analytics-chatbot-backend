from numbers import Number
from typing import Any


MAX_CHART_ITEMS = 10


def is_numeric_value(value: Any) -> bool:
    return isinstance(value, Number) and not isinstance(value, bool)


def find_numeric_keys(data: list[dict]) -> list[str]:
    if not data:
        return []

    keys = list(data[0].keys())

    return [
        key
        for key in keys
        if any(is_numeric_value(row.get(key)) for row in data)
    ]


def find_text_keys(data: list[dict]) -> list[str]:
    if not data:
        return []

    keys = list(data[0].keys())

    return [
        key
        for key in keys
        if any(
            isinstance(row.get(key), str)
            and row.get(key).strip()
            for row in data
        )
    ]


def choose_label_key(
    text_keys: list[str],
    keys: list[str],
) -> str | None:
    preferred_order = [
        "use_name",
        "side_effect_name",
        "substitute_name",
        "medicine_name",
        "chemical_class_name",
        "action_class_name",
        "therapeutic_class_name",
        "client_name",
        "category",
        "label",
        "name",
    ]

    for preferred in preferred_order:
        if preferred in text_keys:
            return preferred

    return text_keys[0] if text_keys else None


def choose_value_key(
    numeric_keys: list[str],
) -> str | None:
    preferred_order = [
        "medicine_count",
        "unique_medicine_count",
        "medicine_record_count",
        "medicine_records",
        "unique_medicine_names",
        "unique_business_medicines",
        "habit_forming_medicine_count",
        "use_count",
        "side_effect_count",
        "substitute_count",
        "occurrence_count",
        "record_count",
        "total_count",
        "count",
        "percentage",
    ]

    for preferred in preferred_order:
        if preferred in numeric_keys:
            return preferred

    return numeric_keys[0] if numeric_keys else None


def to_chart_number(value: Any) -> float | int:
    if not is_numeric_value(value):
        return 0

    numeric_value = float(value)

    if numeric_value.is_integer():
        return int(numeric_value)

    return numeric_value


def format_label(key: str) -> str:
    return key.replace("_", " ").strip().title()


def detect_chart_type(
    question: str,
    label_key: str,
    numeric_keys: list[str],
    row_count: int,
) -> tuple[str | None, str]:
    normalized = question.lower().strip()

    trend_terms = [
        "trend",
        "over time",
        "monthly",
        "yearly",
        "weekly",
        "daily",
        "quarterly",
        "by month",
        "by year",
        "by week",
        "by date",
    ]

    ranking_terms = [
        "top",
        "bottom",
        "highest",
        "lowest",
        "most common",
        "least common",
        "most frequent",
        "least frequent",
    ]

    comparison_terms = [
        "compare",
        "comparison",
        "versus",
        " vs ",
        "by client",
        "across clients",
        "difference between",
    ]

    part_to_whole_terms = [
        "percentage",
        "share",
        "proportion",
        "composition",
        "breakdown",
    ]

    if row_count == 1 and len(numeric_keys) == 1:
        return None, "single_metric"

    if any(term in normalized for term in trend_terms):
        return "line", "trend"

    if any(term in normalized for term in ranking_terms):
        return "bar", "ranking"

    if any(term in normalized for term in comparison_terms):
        return "bar", "comparison"

    if "distribution" in normalized:
        return "bar", "distribution"

    if (
        any(term in normalized for term in part_to_whole_terms)
        and row_count <= 6
    ):
        return "pie", "part_to_whole"

    return "bar", "categorical_comparison"


def prepare_chart_rows(
    rows: list[dict],
    value_key: str,
    chart_reason: str,
) -> list[dict]:
    if chart_reason not in {
        "ranking",
        "distribution",
        "categorical_comparison",
    }:
        return rows[:MAX_CHART_ITEMS]

    sorted_rows = sorted(
        rows,
        key=lambda row: float(row.get(value_key, 0) or 0),
        reverse=True,
    )

    return sorted_rows[:MAX_CHART_ITEMS]


def generate_chart_data(
    data: list[dict],
    question: str = "",
):
    if not data:
        return None

    keys = list(data[0].keys())
    numeric_keys = find_numeric_keys(data)
    text_keys = find_text_keys(data)

    if not numeric_keys or not text_keys:
        return None

    label_key = choose_label_key(text_keys, keys)
    value_key = choose_value_key(numeric_keys)

    if not label_key or not value_key:
        return None

    valid_rows = [
        row
        for row in data
        if row.get(label_key) is not None
        and any(
            is_numeric_value(row.get(key))
            for key in numeric_keys
        )
    ]

    if not valid_rows:
        return None

    chart_type, chart_reason = detect_chart_type(
        question=question,
        label_key=label_key,
        numeric_keys=numeric_keys,
        row_count=len(valid_rows),
    )

    if chart_type is None:
        return None

    chart_rows = prepare_chart_rows(
        rows=valid_rows,
        value_key=value_key,
        chart_reason=chart_reason,
    )

    series = []

    for numeric_key in numeric_keys:
        if any(
            is_numeric_value(row.get(numeric_key))
            for row in chart_rows
        ):
            series.append(
                {
                    "key": numeric_key,
                    "label": format_label(numeric_key),
                    "values": [
                        to_chart_number(row.get(numeric_key))
                        for row in chart_rows
                    ],
                }
            )

    labels = [
        str(row.get(label_key, "Unknown"))
        for row in chart_rows
    ]

    chart = {
        "type": chart_type,
        "reason": chart_reason,
        "xAxis": label_key,
        "labels": labels,
        "series": series,
        "data": chart_rows,
        "limited": len(valid_rows) > len(chart_rows),
        "displayed_items": len(chart_rows),
        "total_items": len(valid_rows),
    }

    # Preserve the old response structure so the existing Angular
    # frontend continues working during the transition.
    chart["yAxis"] = value_key
    chart["values"] = [
        to_chart_number(row.get(value_key))
        for row in chart_rows
    ]

    if chart_reason == "ranking" and len(chart_rows) >= 6:
        chart["orientation"] = "horizontal"
    else:
        chart["orientation"] = "vertical"

    return chart


def generate_insights(data: list[dict]):
    if not data:
        return {
            "record_count": 0,
            "empty": True,
        }

    keys = list(data[0].keys())
    numeric_keys = find_numeric_keys(data)
    text_keys = find_text_keys(data)

    insights = {
        "record_count": len(data),
        "empty": False,
    }

    if not numeric_keys or not text_keys:
        return insights

    value_key = choose_value_key(numeric_keys)
    label_key = choose_label_key(text_keys, keys)

    if not value_key or not label_key:
        return insights

    valid_rows = [
        row
        for row in data
        if is_numeric_value(row.get(value_key))
    ]

    if not valid_rows:
        return insights

    top_item = max(
        valid_rows,
        key=lambda row: float(row.get(value_key, 0)),
    )

    total_value = sum(
        float(row.get(value_key, 0))
        for row in valid_rows
    )

    if total_value.is_integer():
        total_value = int(total_value)

    insights.update(
        {
            "top_category": top_item.get(label_key),
            "top_value": to_chart_number(
                top_item.get(value_key)
            ),
            "total_categories": len(valid_rows),
            "total_value": total_value,
            "label_key": label_key,
            "value_key": value_key,
            "numeric_keys": numeric_keys,
        }
    )

    return insights