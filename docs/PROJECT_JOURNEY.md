# The analysis journey

[Home](../README.md) · [Dashboard](https://charming-brioche-bd8fe4.netlify.app/) · [Method](METHOD.md) · [Validation](EVIDENCE_GUIDE.md)

## Start with a cricket question

The question was which players show the strongest recorded evidence in hard T20 situations. A career average alone cannot answer that: match state and each player's ordinary level matter.

## Make the six files agree

The work began with 200,999 delivery records and 883 matches. Player IDs connected identities; delivery totals were checked against the recorded winning team and result margin. Revised conditions, unfinished games and unresolved scoring problems were separated conservatively, while the original records stayed intact.

## Define pressure before looking at the answer

The four situation components and their weights were declared before rating players. Runs scored or wickets falling on the current ball do not enter that ball's pre-event situation. Ordinary and pressure balls never overlap.

## Keep the inconvenient result

The first separation check did not pass: only 1 of 2 required effects met the cutoff. The weights and acceptance rule were left unchanged. A second comparison within innings stages also left the overall changes uncertain. Both results stayed in the report.

## Compare players cautiously

The model compares each player with his own ordinary level, adjusts for observed context and pulls noisy gains toward zero. Whole-match repeat checks show why exact places should be treated cautiously. Batting runs and boundary gains nearly disappear after shrinkage, so the report explains which components actually drive the gain.

## Try to challenge the ranking

Different settings, match splits, seasons and mixed pressure labels test how much of the order survives. Similar shuffled-label results weaken the case for a distinct pressure advantage. These checks describe limits; they are not hidden or turned into a success claim.

## Make the evidence usable

The output is a working dashboard with player details and comparison, a plain-language presentation, a technical appendix and an ordering-authority CSV. Unexplained range lines became labelled uncertainty tables. A crowded diagnostic page became one paired comparison. The data guide now shows what every file contributes.

## Freeze the result and verify the delivery

Presentation edits leave scores and ranks unchanged. The published study passed 322/322 checks, and the live deployment was compared with the tested files. Only the public review edition is shared here; raw data and private audits remain outside it.

The final lesson is to read a ranking together with its uncertainty and failure modes. A polished list is useful only when its evidence and limits are easy to inspect.
