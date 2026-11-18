# The six datasets

[Home](../README.md) · [Method](METHOD.md) · [Code map](CODE_GUIDE.md)

## Ball-by-ball

**File:** `ball_by_ball.csv` · **Records:** 200,999

Runs, extras, wickets and player IDs. Rebuild the situation before each ball and measure player outcomes.

**Used fields:** `match_id`, `innings`, `batting_team_id`, `bowling_team_id`, `striker_id`, `bowler_id`, `runs`, `extras_type`, `extras1_runs`, `extras_2_runs`, `is_wicket`, `dismissed_player_id`, `is_four`, `is_six`, `batting_order`, `pace_or_spin`.

## Matches

**File:** `matches.csv` · **Records:** 883

Dates, venue IDs, knockout flags and results. Add match context; check the reconstructed winner and margin.

**Used fields:** `match_id`, `comp_id`, `match_date`, `venue_id`, `knock_out`, `win_team_id`, `result`, `first_inn_revised_overs`, `second_inn_revised_overs`, `revised_target`.

## Competitions

**File:** `competitions.csv` · **Records:** 141

Competition names, seasons and formats. Separate IPL, T20I and emerging-team T20; compare seasons.

**Used fields:** `comp_id`, `comp_name`, `season`, `match_format`.

## Teams

**File:** `teams.csv` · **Records:** 353

Team IDs and their recorded names. Identify the opposition and display consistent team labels.

**Used fields:** `comp_id`, `team_id`, `team_name`.

## Player identity mapping

**File:** `competition_team_player_mapping.csv` · **Records:** 6,413

Canonical player IDs and names across teams. Resolve one identity across files; never match players by a guessed name.

**Used fields:** `comp_id`, `team_id`, `player_id`, `player_name`.

## Playing XIs

**File:** `playing_eleven.csv` · **Records:** 28,381

Line-ups, played flags and team membership. Check participation and attach the latest observed team in the pack.

**Used fields:** `match_id`, `team_id`, `player_id`, `is_played`.

## How the files connect

`match_id` connects balls and line-ups to matches. `comp_id` connects competitions; `comp_id` plus `team_id` identifies a team within competition context. `player_id` connects the same player across all records. Names are taken from the canonical mapping, not guessed.

## Used for roles, not scoring weights

Batting position and pace/spin describe observed player usage. Speed, stroke and delivery-style labels are not inputs to the rating formula.

## Public-data boundary

The counts and field descriptions are published, not the proprietary raw rows or private identity evidence. The public dashboard and ranking files contain the approved derived results. See [reproduction notes](REPRODUCIBILITY.md).
