# Checks and limitations

[Home](../README.md) · [Method](METHOD.md) · [Data guide](DATA_GUIDE.md)

## What passed computational verification

The study passed **322/322 automated checks**. Those checks cover frozen numerical values, identity boundaries, ordering across the PDF/slides/CSV/dashboard, native presentation evidence, text preservation and responsive behaviour.

Scoring reconstruction agreed with the winning team in 814/814 non-DLS matches, and with the margin in 812/814. Unresolved mismatches remain outside the model. The quality mask removes 88/883 matches and 11,259/200,999 physical records; historical-benchmark warm-up is a separate step.

## What did not pass scientifically

The initial separation criterion required two clear rate changes. Only dismissal met it. Dot-rate separation was modest and boundary separation negligible. All six overall ranges include no change after matching innings and stages.

The label-mixing check preserves much of the order. Match splits and year comparisons show limited stability. Batting runs and boundaries shrink nearly to the configured floor, so dismissals and dots dominate the shrunk batting gain.

Software checks passing do not make these scientific limitations disappear. The ratings do not establish causality, a separate psychological pressure trait or predictive accuracy.

## How to read the ranges

The uncertainty draws keep fitted context, priors and scales fixed. Player resamples are separate and omit shared-match covariance. The rank ranges and top-ten frequencies use the original comparison pool before the individual display exclusion. They are conditional diagnostics, not forecasts.

Diagnostic cohort counts precede selection exclusions, so they can differ from the public candidate counts. No excluded player's identity is published in these tables.

## Evidence files

- [Pooled pressure versus ordinary rates and effects](../outputs/pressure_separation.csv)
- [Like-for-like overall comparison](../outputs/secondary_separation_standardized.csv)
- [Every innings-stage comparison](../outputs/secondary_separation_by_stratum.csv)
- [Match splits, seasons and calendar years](../outputs/reliability_summary.csv)
- [All declared alternative settings](../outputs/sensitivity_summary.csv)
- [Every shuffled-label repetition](../outputs/placebo_results.csv)
- [Quality losses by competition class](../outputs/quarantine_by_class.csv)
- [Quality losses by season](../outputs/quarantine_by_season.csv)
- [Quality reasons, including overlapping reasons](../outputs/quarantine_by_reason.csv)
- [Non-overlapping primary quality reasons](../outputs/quarantine_exclusive_reason.csv)
- [All recorded reconstruction mismatches](../outputs/match_reconciliation_mismatches.csv)

[Technical appendix: report pages 13–20](../report/RR_Pressure_Reliability_Methodology.pdf)
