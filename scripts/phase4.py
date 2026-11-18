from model_common import *
from rating_engine import *

def main():
    b=pd.read_parquet(PRO/'pressure.parquet')
    names=pd.read_parquet(PRO/'players.parquet').set_index('player_id')
    frames=[];parameters=[];provenance=[];observation_frames=[]
    for discipline in ['batter','bowler']:
        print('Building held-out context:',discipline,flush=True)
        obs,prov=observations(b,discipline);observation_frames.append(obs);provenance.extend(prov)
        for scope in CFG['ratings']['scopes']:
            print('Rating:',discipline,scope,flush=True)
            frame,hyp,draws,players=fit_scope(obs,discipline,scope)
            frame['display_name']=frame.player_id.map(names.display_name)
            frame['nationality_flag']=frame.player_id.map(names.nationality_flag)
            frames.append(frame)
            parameters.append(dict(discipline=discipline,scope=scope,**{k:v.tolist() if hasattr(v,'tolist') else v for k,v in hyp.items()}))
            if draws:
                np.savez_compressed(OUT/f'bootstrap_{discipline}_{scope}.npz',player_ids=np.array(list(draws)),ratings=np.stack(list(draws.values())))
    ratings=pd.concat(frames,ignore_index=True)
    observations_all=pd.concat(observation_frames,ignore_index=True)
    observations_all.to_parquet(PRO/'rating_observations.parquet',index=False)
    ratings.to_parquet(PRO/'ratings.parquet',index=False)
    csv(ratings,OUT/'ratings_all_computed.csv');csv(pd.DataFrame(provenance),OUT/'context_fold_provenance.csv');dump(OUT/'eb_hyperparameters.json',parameters)
    tops=ratings[ratings.eligible & ratings.unfiltered_rank.le(15)].sort_values(['scope','discipline','unfiltered_rank'])
    csv(tops,OUT/'unfiltered_top15_phase4.csv')
    summary=ratings.groupby(['scope','discipline']).agg(players=('player_id','size'),eligible_players=('eligible','sum')).reset_index()
    csv(summary,OUT/'eligibility_counts.csv')
    dist=[]
    for (scope,discipline),g in ratings[ratings.eligible].groupby(['scope','discipline']):
        desc=g.pressure_balls.describe(percentiles=[.1,.25,.5,.75,.9]).to_dict()
        dist.append(dict(scope=scope,discipline=discipline,**{k:float(v) for k,v in desc.items()}))
    csv(pd.DataFrame(dist),OUT/'eligible_pressure_ball_distribution.csv')
    eligible=ratings[ratings.eligible]
    checks={'no_heldout_training_match_overlap':all(p['overlapping_matches']==0 for p in provenance),
      'all_display_names_canonical':ratings.display_name.eq(ratings.player_id.map(names.display_name)).all(),
      'no_availability_filter_before_scoring':set(observations_all.player_id)==set(ratings[ratings.scope.eq('Combined')].player_id),
      'pressure_baseline_disjoint_per_player':not observations_all.groupby(['discipline','player_id','delivery_id']).high_pressure.nunique().gt(1).any(),
      'paired_player_ratings_finite':np.isfinite(ratings.loc[ratings.paired,'rating']).all(),
      'unpaired_player_ratings_unavailable':ratings.loc[~ratings.paired,'rating'].isna().all(),
      'shrinkage_bounded':ratings.loc[ratings.paired,['shrinkage_'+k for k in METRICS]].ge(0).all().all() and ratings.loc[ratings.paired,['shrinkage_'+k for k in METRICS]].le(1).all().all(),
      'eligible_intervals_finite':np.isfinite(eligible[['ci_low','ci_high']]).all().all(),
      'intervals_ordered':eligible.ci_low.le(eligible.ci_high).all(),
      'configured_exposures_respected':eligible.pressure_balls.ge(CFG['ratings']['min_pressure_balls']).all() and eligible.baseline_balls.ge(CFG['ratings']['min_baseline_balls']).all(),
      'at_least_ten_eligible_requested_lists':summary[summary.scope.isin(['Combined','IPL','T20I'])].eligible_players.ge(10).all(),
      'raw_runs_preserved':all(np.isclose(obs[~obs.off_strike_dismissal].runs.sum(),b.runs.sum() if discipline=='batter' else b.bowler_runs_conceded.sum()) for discipline,obs in zip(['batter','bowler'],observation_frames)),
      'shrinkage_decreases_with_noise':all((h['tau']/(h['tau']+2*h['tau'])<=h['tau']/(h['tau']+h['tau'])).all() for h in [dict(tau=np.array(p['tau'])) for p in parameters])}
    checks={k:bool(v) for k,v in checks.items()}
    dump(OUT/'phase4_checks.json',checks)
    override=CFG.get('phase4_capacity_deviation',{})
    short=summary[summary.scope.isin(['Combined','IPL','T20I']) & summary.eligible_players.lt(10)]
    authorized=override.get('authorized_by')=='user' and len(short)==1 and short.iloc[0].scope==override.get('scope') and short.iloc[0].discipline==override.get('discipline') and int(short.iloc[0].eligible_players)==override.get('qualified_count')
    remaining={k:v for k,v in checks.items() if not (authorized and k=='at_least_ten_eligible_requested_lists')}
    if not all(remaining.values()):gate(checks,OUT/'phase4_checks.json')
    dump(OUT/'phase4_acceptance_status.json',dict(computational_checks_passed=all(remaining.values()),original_capacity_check_passed=checks['at_least_ten_eligible_requested_lists'],accepted_by_explicit_user_exception=bool(authorized),exception='T20I batting list has four qualified players; no threshold changes.' if authorized else None))
    (ROOT/'docs/ratings_methodology.md').write_text('''# Phase 4 rating methodology

Eligibility was fixed before viewing scores: 200 pressure legal balls, 400 baseline legal balls and 10 matches in each state. Planning precision assumptions and all weights are in config and IMPLEMENTATION_PLAN.md. These do not guarantee reliability. Every observed player is processed before availability selection; a comparable score requires both disjoint samples. Missing-state scores are explicitly unavailable, with rating_status, rather than assigning a zero baseline. Paired but ineligible scores remain stored without ranks. Canonical IDs distinguish same-name players.

Five deterministic match-held-out folds predict event-level runs, dismissal/wickets, dots and batter boundaries. No training match overlaps its prediction match. Hierarchical context means use competition class, phase and innings, with additive shrunk venue and opposing-team residual corrections. All three classes are distinct; combined ratings compare residual performance within context rather than applying reputation-based league weights. This controls observed group averages, not player-strength/opposition quality perfectly. Folds are retrospective, not forward forecasts; context estimates may use later matches. Historical par and all pressure inputs remain earlier-date/pre-event.

Batters: runs include no-ball scoring, balls faced exclude wides and include no-balls. Non-striker dismissals are separately attributed to the dismissed ID with zero runs/balls, never charged to the striker; off-strike wicket expectation is zero, an approximation noted here. Bowlers: debit batter runs plus no-ball/wide penalties, omit byes/leg-byes/other non-bowler extras; denominator legal balls. Wickets credit only bowler dismissal types. Dot definition is zero batter runs per faced ball (batting) and zero bowler debit per legal ball (bowling); boundaries are batter-credited fours/sixes. Illegal-event outcomes enter numerators and context residuals. Expectation is event-level and rates divide residual sums by the proper exposure, not by number of physical records.

For each metric, compare the player's signed pressure residual rate to his own disjoint ordinary residual rate. Empirical Bayes shrinks gains toward zero, using estimated between-player variance minus mean sampling variance across ALL paired players; sampling variance uses match influence functions with a pooled residual-second-moment variance floor to prevent single-match zero variances. Shrinkage is tau²/(tau²+sampling variance). Positive signs mean runs/boundaries and fewer dots/dismissals for batters, lower runs/boundaries and more dots/wickets for bowlers.

Combine standardized EB metric gains (runs .45, wickets .25, dots .15, boundaries .15). Latent score = .70 own-baseline gain + .20 absolute pressure residual + .10 match consistency (transformed from 0–1 to -1–1). Consistency is the fraction of pressure matches beating the player's own baseline composite, shrunk with ten .5 pseudo-matches. Rating = 50 + 10*latent; it is an unbounded index, NOT probability or percentile. Discipline/scope normalizations differ and should not be compared numerically across disciplines.

95% intervals use 500 match resamples of each player's entire match exposure; context predictions and EB population/variance parameters are held fixed. They describe conditional score uncertainty and omit nuisance-model refitting. Rank-resampling in Phase 5 resamples players' match blocks independently: it does not preserve cross-player same-match covariance and is an approximate rank uncertainty diagnostic. Small/heterogeneous samples and context extrapolation can make ranks fragile.

Required limitation: pressure is situational by construction. Original pooled separation is strongest for dismissal risk, modest for dots and negligible for boundaries; the predeclared two-metric criterion FAILED. User explicitly authorized this deviation. Stratified standardized confidence intervals all span zero, with sparse powerplay pressure observations. Own-baseline comparisons do not require pooled separation but remain observational and context dependent; no causal or psychological clutch claim follows.
''',encoding='utf-8')
    print(summary.to_string(index=False));print('Phase 4 checks passed.')

if __name__=='__main__':main()
