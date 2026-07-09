import re

ALLOWED_TABLES = [
    "pharma-ai-dashboard.pharma_warehouse.medicines_master",
    "pharma-ai-dashboard.pharma_warehouse.clients",
    "pharma-ai-dashboard.pharma_warehouse.action_classes",
    "pharma-ai-dashboard.pharma_warehouse.chemical_classes",
    "pharma-ai-dashboard.pharma_warehouse.uses",
    "pharma-ai-dashboard.pharma_warehouse.side_effects",
    "pharma-ai-dashboard.pharma_warehouse.substitutes",
    "pharma-ai-dashboard.pharma_warehouse.medicine_uses",
    "pharma-ai-dashboard.pharma_warehouse.medicine_side_effects",
    "pharma-ai-dashboard.pharma_warehouse.medicine_substitutes",
]

BLOCKED_SQL_WORDS = [
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


def validate_sql(sql: str) -> bool:
    if not sql:
        return False

    cleaned = sql.strip().lower()

    if not cleaned.startswith("select"):
        return False

    if "```" in cleaned:
        return False

    if "your_dataset" in cleaned or "your_table" in cleaned:
        return False

    for word in BLOCKED_SQL_WORDS:
        if re.search(rf"\b{word}\b", cleaned):
            return False

    if not any(table in cleaned for table in ALLOWED_TABLES):
        return False

    return True