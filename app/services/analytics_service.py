def choose_label_key(text_keys: list, keys: list):
    preferred_order = [
        "use_name",
        "side_effect_name",
        "substitute_name",
        "medicine_name",
        "chemical_class_name",
        "action_class_name",
        "therapeutic_class_name",
        "client_name",
    ]

    for preferred in preferred_order:
        if preferred in text_keys:
            return preferred

    return text_keys[0] if text_keys else None


def choose_value_key(numeric_keys: list):
    preferred_order = [
        "medicine_count",
        "habit_forming_medicine_count",
        "use_count",
        "side_effect_count",
        "substitute_count",
        "occurrence_count",
        "total_count",
        "count",
    ]

    for preferred in preferred_order:
        if preferred in numeric_keys:
            return preferred

    return numeric_keys[0] if numeric_keys else None


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

    value_key = choose_value_key(numeric_keys)
    label_key = choose_label_key(text_keys, keys)

    if not value_key or not label_key:
        return None

    labels = [str(row.get(label_key, "")) for row in data]
    values = [row.get(value_key, 0) for row in data]

    chart_type = "bar"

    if len(labels) <= 6 and label_key == "client_name":
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

    numeric_keys = [
        key for key in keys
        if isinstance(first_row.get(key), (int, float))
    ]

    text_keys = [
        key for key in keys
        if isinstance(first_row.get(key), str)
    ]

    if numeric_keys and text_keys:
        value_key = choose_value_key(numeric_keys)
        label_key = choose_label_key(text_keys, keys)

        if not value_key or not label_key:
            return {"record_count": len(data)}

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