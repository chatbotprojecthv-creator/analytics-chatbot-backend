from google import genai
from app.config import GEMINI_API_KEY

client = genai.Client(api_key=GEMINI_API_KEY)


def generate_sql(question: str, schema: list):

    prompt = f"""
    You are a BigQuery SQL expert.

    Convert the user's question into a valid BigQuery SQL query.

    Rules:
    - Only generate SELECT queries
    - Do not generate DELETE, DROP, UPDATE, INSERT
    - Use only the provided schema
    - Return ONLY SQL

    Table Schema:
    {schema}

    User Question:
    {question}
    """

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )

    return response.text.strip()