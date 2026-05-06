"""
Regression evaluator for SDD-007 transformers-nlp-backend.

Spec reference: SDD/requirements/SPEC-007-transformers-nlp-backend.md
Dataset: regression-transformers-nlp-backend

Comparison shape: set of (entity_type, start, end) tuples per text.
Metrics: precision, recall, F1.

IMPORTANT (langsmith-evaluator Golden Rule):
Before trusting this evaluator, run the feature on 2-3 real inputs,
inspect the actual analyzer output, and verify _extract_output's tuple
extraction matches what the analyzer returns.
"""
from typing import Set, Tuple


def _extract_output(run) -> Set[Tuple[str, int, int]]:
    """Extract (entity_type, start, end) tuples from a run."""
    outputs = run.outputs if hasattr(run, "outputs") else run.get("outputs", {})
    entities = outputs.get("entities", [])
    return {(e["entity_type"], e["start"], e["end"]) for e in entities}


def _extract_expected(example) -> Set[Tuple[str, int, int]]:
    """Extract expected entity tuples from a dataset example."""
    expected = example.outputs if hasattr(example, "outputs") else example.get("outputs", {})
    entities = expected.get("entities", [])
    return {(e["entity_type"], e["start"], e["end"]) for e in entities}


def precision_recall_f1(run, example) -> dict:
    """Compute precision / recall / F1 against the expected entity set.

    Returns {score: float, comment: str} where score is F1.
    """
    actual = _extract_output(run)
    expected = _extract_expected(example)

    if not actual and not expected:
        return {"score": 1.0, "comment": "Both empty (correctly identified no entities)."}
    if not actual:
        return {"score": 0.0, "comment": f"Found 0 entities; expected {len(expected)}: {expected}."}
    if not expected:
        return {"score": 0.0, "comment": f"Found {len(actual)} entities; expected 0 (over-detection): {actual}."}

    tp = len(actual & expected)
    fp = len(actual - expected)
    fn = len(expected - actual)

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    comment = f"P={precision:.3f} R={recall:.3f} F1={f1:.3f}; missing={expected - actual}; spurious={actual - expected}"
    return {"score": f1, "comment": comment}


# REQ-XXX bindings (for the langsmith-evaluator skill to know what this evaluator covers):
# - REQ-001: MultiNlpEngine routing — verified by precision/recall on per-language inputs.
# - REQ-006/007: threshold tuning — verified by detection-set match on labeled examples.
# - REQ-008/009: broader-class — over-detection captured in `spurious` set.
# - REQ-009b: held-out positive — DE LOCATION true-positive verified by precision/recall.
