# How PressureIndex is calculated

[Home](../README.md) · [Data guide](DATA_GUIDE.md) · [Validation](EVIDENCE_GUIDE.md) · [Report](../report/RR_Pressure_Reliability_Methodology.pdf)

## 1. Rebuild the match state

Sort the delivery records and reconstruct runs, wickets and legal balls before each event. Join match dates, competition context, venue IDs and the knockout flag. Keep the legal-ball count distinct from physical event records: wides and no-balls affect those counts differently.

The historical scoring benchmark uses strictly earlier dates, with class and venue pooling. Matches without enough earlier evidence do not receive an invented benchmark.

## 2. Score the situation

The four bounded inputs are urgency (35%), wicket scarcity (25%), scoring demand (30%) and knockout context (10%). Their normalized sum gives a 0–100 score before the delivery.

High pressure is the legal-ball 75th percentile within each innings type: **42.3574** in the first innings and **39.3968** in the second. Apply those cutoffs to all events. The ordinary group is the disjoint complement.

These categories are retrospective. Using a situational definition does not measure a player's feelings or establish a psychological trait.

## 3. Compare each player with his own baseline

Estimate runs, dismissals/wickets, dots and boundaries relative to context. Five match-held-out groups use competition class, innings and stage, followed by venue and opposition corrections. Held-out matches do not train their own expectations; the groups are retrospective rather than a future prediction test.

Batting uses balls faced, including no-balls and excluding wides. Bowling uses legal balls. Illegal-event runs still enter the numerators. Canonical player IDs define identity.

## 4. Apply caution and combine the evidence

Noisy component gains are pulled toward zero using empirical-Bayes shrinkage. All paired players inform the population scales before selection.

Component weights are runs 45%, wickets/dismissals 25%, dots 15% and boundaries 15%.

The index combines 70% own-baseline gain, 20% contextual pressure performance and 10% match consistency. The centre is 50; batting and bowling use their own scales.

## 5. Show uncertainty and apply selection

Pick whole matches again 500 times per player. The middle 95% gives conditional score/rank ranges. Seed 20261115 is the saved starting value for repeatable random draws. Context fits, priors and scales stay fixed; separate player resamples omit some shared-match uncertainty.

The displayed order applies the selection constraints after fitting. The earlier comparison-pool rank ranges and top-ten frequencies are preserved. Do not read a small score gap as a certain difference in place.

The full formulas, variance floor and all diagnostic tables are on report pages 13–20. [Open the technical appendix](https://charming-brioche-bd8fe4.netlify.app/report/RR_Pressure_Reliability_Methodology.pdf#page=13).
