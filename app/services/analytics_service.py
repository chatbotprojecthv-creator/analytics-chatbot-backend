def generate_chart_data(data: list):
    if not data:
        return None

    first_row = data[0]
    keys = list(first_row.keys())

    numeric_keys = [
        key for key in keys
        if isinstance(first_row.get(key), (int, float))
    ]

    text_keys = [
        key for key in keys
        if isinstance(first_row.get(key), str)
    ]

    if not numeric_keys or not text_keys:
        return None

    value_key = numeric_keys[0]
    label_key = text_keys[0]

    labels = [str(row.get(label_key, "")) for row in data]
    values = [row.get(value_key, 0) for row in data]

    chart_type = "bar"

    if len(labels) <= 6:
        chart_type = "pie"

    return {
        "type": chart_type,
        "xAxis": label_key,
        "yAxis": value_key,
        "labels": labels,
        "values": values
    }


def generate_insights(data: list):
    if not data:
        return {}

    first_row = data[0]
    keys = list(first_row.keys())

    if "side_effect_count" in keys:
        return {
            "medicine_with_most_side_effects": first_row.get("medicine_name"),
            "side_effect_count": first_row.get("side_effect_count")
        }

    if "medicine_name" in keys and any(key.startswith("use_") for key in keys):
        uses = [
            first_row.get("use_0"),
            first_row.get("use_1"),
            first_row.get("use_2"),
            first_row.get("use_3"),
            first_row.get("use_4")
        ]

        uses = [use for use in uses if use]

        return {
            "medicine_found": True,
            "medicine_name": first_row.get("medicine_name"),
            "uses": uses,
            "therapeutic_class": first_row.get("therapeutic_class"),
            "action_class": first_row.get("action_class")
        }

    numeric_keys = [
        key for key in keys
        if isinstance(first_row.get(key), (int, float))
    ]

    text_keys = [
        key for key in keys
        if isinstance(first_row.get(key), str)
    ]

    if numeric_keys and text_keys:
        value_key = numeric_keys[0]
        label_key = text_keys[0]

        top_item = max(data, key=lambda row: row.get(value_key, 0))

        total_value = sum(
            row.get(value_key, 0)
            for row in data
            if isinstance(row.get(value_key), (int, float))
        )

        return {
            "top_category": top_item.get(label_key),
            "top_value": top_item.get(value_key),
            "total_categories": len(data),
            "total_value": total_value,
            "label_key": label_key,
            "value_key": value_key
        }

    return {
        "record_count": len(data)
    }