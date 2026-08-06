import re
from typing import Final


ALLOWED_TABLES: Final[set[str]] = {
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
}


BLOCKED_SQL_KEYWORDS: Final[set[str]] = {
    "alter",
    "call",
    "create",
    "delete",
    "drop",
    "execute",
    "export",
    "grant",
    "insert",
    "load",
    "merge",
    "revoke",
    "truncate",
    "update",
}


PLACEHOLDER_PATTERNS: Final[set[str]] = {
    "your_project",
    "your_dataset",
    "your_table",
    "project.dataset",
    "dataset.table",
}


def _strip_comments(sql: str) -> str:
    without_block_comments = re.sub(
        r"/\*.*?\*/",
        " ",
        sql,
        flags=re.DOTALL,
    )

    without_dash_comments = re.sub(
        r"--[^\n\r]*",
        " ",
        without_block_comments,
    )

    return re.sub(
        r"#[^\n\r]*",
        " ",
        without_dash_comments,
    )


def _strip_string_literals(sql: str) -> str:
    without_single_quotes = re.sub(
        r"'(?:''|\\'|[^'])*'",
        "''",
        sql,
        flags=re.DOTALL,
    )

    return re.sub(
        r'"(?:""|\\\"|[^"])*"',
        '""',
        without_single_quotes,
        flags=re.DOTALL,
    )


def _has_multiple_statements(sql: str) -> bool:
    cleaned = sql.strip()

    if cleaned.endswith(";"):
        cleaned = cleaned[:-1].rstrip()

    return ";" in cleaned


def _extract_referenced_tables(sql: str) -> set[str]:
    pattern = re.compile(
        r"\b(?:from|join)\s+`([^`]+)`",
        flags=re.IGNORECASE,
    )

    return {
        table.strip().lower()
        for table in pattern.findall(sql)
    }


def _contains_unquoted_physical_table(sql: str) -> bool:
    sql_without_backticked_names = re.sub(
        r"`[^`]+`",
        " ",
        sql,
    )

    return bool(
        re.search(
            r"\bpharma-ai-dashboard\s*\.",
            sql_without_backticked_names,
            flags=re.IGNORECASE,
        )
    )


def validate_sql(sql: str) -> bool:
    """
    Validate generated BigQuery SQL before execution.

    Accepted:
    - SELECT statements
    - WITH ... SELECT statements
    - One read-only statement
    - Approved warehouse tables only
    - Fully qualified, backticked physical table names
    """
    if not isinstance(sql, str) or not sql.strip():
        return False

    cleaned = sql.strip()

    if "```" in cleaned:
        return False

    if _has_multiple_statements(cleaned):
        return False

    sql_without_comments = _strip_comments(cleaned)
    lowered = sql_without_comments.lower().strip()

    if not re.match(r"^(select|with)\b", lowered):
        return False

    for placeholder in PLACEHOLDER_PATTERNS:
        if placeholder in lowered:
            return False

    sql_without_literals = _strip_string_literals(lowered)

    for keyword in BLOCKED_SQL_KEYWORDS:
        if re.search(
            rf"\b{re.escape(keyword)}\b",
            sql_without_literals,
        ):
            return False

    referenced_tables = _extract_referenced_tables(sql_without_comments)

    if not referenced_tables:
        return False

    if not referenced_tables.issubset(ALLOWED_TABLES):
        return False

    if _contains_unquoted_physical_table(sql_without_comments):
        return False

    return True