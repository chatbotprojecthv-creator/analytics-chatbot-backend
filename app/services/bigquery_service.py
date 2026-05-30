from google.cloud import bigquery
from app.config import PROJECT_ID

client = bigquery.Client(project=PROJECT_ID)


def test_connection(table_name: str):
    query = f"""
    SELECT COUNT(*) AS total_records
    FROM `{table_name}`
    """

    result = client.query(query).to_dataframe()
    return result.to_dict(orient="records")[0]


def get_schema(table_name: str):
    table = client.get_table(table_name)

    schema = []

    for field in table.schema:
        schema.append({
            "name": field.name,
            "type": field.field_type
        })

    return schema


def run_sql(sql: str):
    result = client.query(sql).to_dataframe()
    return result.to_dict(orient="records")