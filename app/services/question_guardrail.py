from typing import Dict, Any

ALLOWED_KEYWORDS = [
    "medicine", "medicines", "drug", "drugs",
    "client", "clients",
    "side effect", "side effects",
    "use", "uses", "usage",
    "therapeutic", "chemical", "action class",
    "habit forming", "habit-forming",
    "substitute", "substitutes",
    "inventory", "stock",
    "sales", "manufacturer", "prescription",
    "count", "compare", "top", "highest", "lowest", "common"
]

BLOCKED_MEDICAL_WORDS = [
    "recommend", "suggest", "prescribe", "dosage", "dose",
    "cure", "treat", "treatment", "take medicine",
    "what should i take", "for fever", "for pain",
    "stomach pain", "headache", "hangover"
]

def is_medical_advice_request(question: str) -> bool:
    q = question.lower()
    return any(word in q for word in BLOCKED_MEDICAL_WORDS)

def is_pharma_analytics_question(question: str) -> bool:
    q = question.lower()
    return any(word in q for word in ALLOWED_KEYWORDS)

def guardrail_response(message: str) -> Dict[str, Any]:
    return {
        "sql": None,
        "summary": message,
        "insights": {},
        "chart": None,
        "data": []
    }

def validate_question_scope(question: str):
    if is_medical_advice_request(question):
        return guardrail_response(
            "Oops, I can’t provide medical recommendations. "
            "I can help with pharma analytics, reporting, medicine counts, side effects, uses, clients, and warehouse insights."
        )

    if not is_pharma_analytics_question(question):
        return guardrail_response(
            "This question is outside the scope of the Pharma Analytics database. "
            "Please ask about medicines, clients, uses, side effects, substitutes, inventory, sales, or client comparisons."
        )

    return None