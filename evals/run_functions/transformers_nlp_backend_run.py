"""
Run function for SDD-007 transformers-nlp-backend.

Wraps the Redakt /api/detect endpoint so LangSmith's evaluate() can replay
dataset inputs against it.

Dataset shape: { "text": str, "language": str | "auto" } -> { "entities": [...] }
"""
import os
import requests

REDAKT_BASE_URL = os.getenv("REDAKT_BASE_URL", "http://localhost:8000")


def run_feature(inputs: dict) -> dict:
    """Invoke Redakt /api/detect with dataset inputs.

    Args:
        inputs: {"text": str, "language": "en" | "de" | "auto" (default)}

    Returns:
        {"entities": [{"entity_type": str, "start": int, "end": int, "score": float}, ...]}
    """
    text = inputs["text"]
    language = inputs.get("language", "auto")

    response = requests.post(
        f"{REDAKT_BASE_URL}/api/detect",
        json={"text": text, "language": language},
        timeout=30,
    )
    response.raise_for_status()
    body = response.json()

    # Adapt response shape if needed. Redakt's /api/detect returns the
    # entity list directly or under an "entities" key — verify the shape
    # before populating golden examples (langsmith-evaluator Golden Rule).
    entities = body.get("entities", body if isinstance(body, list) else [])
    return {"entities": entities}


if __name__ == "__main__":
    # Local smoke test before running full eval.
    sample = {"text": "John Smith works at Acme Corp.", "language": "en"}
    print(run_feature(sample))
