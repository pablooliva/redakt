# Redakt Regression Evals

LangSmith-backed regression eval scaffolding for Redakt features whose specs
have `eval_required: true`. The canonical dataset lives in LangSmith; the
`datasets/*.json` files here are local stubs that mirror it.

## Layout

```
evals/
├── README.md                           # this file
├── datasets/                           # local mirrors of LangSmith datasets
├── evaluators/                         # one Python module per feature
└── run_functions/                      # one Python module per feature
```

Each feature has matching `evaluators/<feature>_evaluator.py` and
`run_functions/<feature>_run.py`. The run function replays a dataset input
against the feature (typically by hitting the running Redakt API). The
evaluator scores the run output against the expected dataset output.

## Datasets

| Dataset name | Feature | Spec | Status | Examples | Notes |
|---|---|---|---|---|---|
| regression-transformers-nlp-backend | transformers-nlp-backend | SPEC-007-transformers-nlp-backend.md | needs-population | 0 | Created 2026-05-06; populate after >=1 week of runtime |

## Prerequisites

- `langsmith` CLI installed (`uv pip install langsmith` or system install).
- `LANGSMITH_API_KEY` exported.
- `LANGSMITH_PROJECT` exported (or set in `.env`).

## Workflow

1. **Scaffold** — `regression-eval-capture` runs at SDD Step 4g and creates the
   evaluator + run function stubs plus an empty local dataset file. If
   prerequisites are missing it still writes the stubs but skips LangSmith
   dataset creation; a warning is logged in `SDD/orchestration/progress.md`.
2. **Populate** — after >=1 week of feature runtime, capture 10-20 representative
   golden examples (positive, negative, edge) and upload to LangSmith.
3. **Run** — `langsmith` CLI or `evaluate()` from the SDK against the dataset
   using the run function and evaluator.
4. **Verify** — Inspect outputs on 2-3 real inputs first to confirm the
   evaluator's extraction logic matches the actual response shape (the
   langsmith-evaluator Golden Rule).
