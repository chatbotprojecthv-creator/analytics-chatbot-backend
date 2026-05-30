import re


def validate_sql(sql: str, table_name: str) -> bool:
    if not sql:
        return False

    cleaned = sql.strip().lower()

    if not cleaned.startswith("select"):
        return False

    blocked_words = [
        "delete",
        "drop",
        "truncate",
        "insert",
        "update",
        "merge",
        "alter",
        "create",
        "grant",
        "revoke"
    ]

    for word in blocked_words:
        if re.search(rf"\b{word}\b", cleaned):
            return False

    expected_table = f"`{table_name}`".lower()

    if expected_table not in cleaned:
        return False

    if "your_dataset" in cleaned or "your_table" in cleaned:
        return False

    if "```" in cleaned:
        return False

    return True