# Code map

[Home](../README.md) · [Method](METHOD.md) · [Run and reproduce](REPRODUCIBILITY.md)

## Analytical reference

- [Input profiling and reconciliation](../scripts/phase1.py): schemas, legal events, score totals, participation and identity construction.
- [Pre-ball features](../scripts/phase2.py): match state and strictly earlier-date historical scoring benchmarks.
- [Pressure definition](../scripts/phase3.py): bounded components, innings-specific cutoffs and the original separation check.
- [Within-stage separation](../scripts/secondary_separation.py): clustered comparisons within phase and innings.
- [Rating engine](../scripts/rating_engine.py): context expectations, own baselines, shrinkage, index and match resampling.
- [Rating orchestration](../scripts/phase4.py): fitting by discipline and competition scope.
- [Robustness checks](../scripts/phase5.py): splits, time stability, alternative settings and label mixing.
- [Model settings](../config.yaml): the declared weights, thresholds, minimum exposure and seeds.

These files document the calculations. A numerical refit needs the licensed records and full private evidence pipeline; the public preview does not execute them. Publication only neutralizes operator-facing prose in source messages; numerical expressions and settings are preserved.

## Frontend

- [Dashboard component](../dashboard/src/App.tsx): ranking controls, player details, comparison, explanations and copy order.
- [Presentation styles](../dashboard/src/premium.css): the navy/pink/paper layout and responsive source guide.
- [Dashboard data](../dashboard/public/dashboard_data.json): the frozen public results used by the interface.

## Public review tools

[review.py](../review.py) verifies the public snapshot and serves the prebuilt website. It uses Python's standard library and never fits models or reads private data.
