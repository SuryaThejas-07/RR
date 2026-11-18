from model_common import *

def main():
    all_b=pd.read_parquet(PRO/'deliveries.parquet')
    b=all_b[all_b.analysis_candidate & all_b.is_regular_innings].copy().sort_values('delivery_id')
    m=pd.read_parquet(PRO/'matches.parquet')
    m=m[m.analysis_candidate].copy().sort_values(['match_date','match_id'])
    f=CFG['features'];balls=CFG['data']['normal_innings_balls'];wickets=CFG['data']['wickets_per_innings'];bpo=CFG['data']['balls_per_over']
    group=b.groupby(['match_id','innings'],sort=False)
    b['legal_balls_before']=group.is_legal.cumsum()-b.is_legal.astype(int)
    b['runs_before']=group.total_runs.cumsum()-b.total_runs
    b['wickets_before']=group.is_wicket.cumsum()-b.is_wicket.astype(int)
    b['wickets_in_hand']=wickets-b.wickets_before
    b['balls_remaining']=balls-b.legal_balls_before
    b['current_run_rate']=np.where(b.legal_balls_before.gt(0),bpo*b.runs_before/b.legal_balls_before.replace(0,np.nan),0)
    b['target']=b.derived_chase_target.where(b.innings.eq(2))
    b['runs_required']=b.target-b.runs_before
    b['required_run_rate']=bpo*b.runs_required/b.balls_remaining
    b['rrr_gap']=b.required_run_rate-b.current_run_rate
    b['phase']=np.select([b.legal_balls_before.lt(f['powerplay_end']),b.legal_balls_before.lt(f['middle_end'])],['powerplay','middle'],default='death')
    first=b[b.innings.eq(1)].groupby('match_id').total_runs.sum().rename('first_total')
    hist=m[['match_id','match_date','competition_class','venue_id','knock_out']].merge(first,on='match_id',validate='one_to_one')
    # Accumulate only after processing every match on a date, preventing same-day leakage.
    global_scores=[];class_scores={};venue_scores={};par_records=[]
    for date,daily in hist.groupby('match_date',sort=True):
        for row in daily.itertuples():
            cl=class_scores.get(row.competition_class,[])
            ve=venue_scores.get((row.competition_class,row.venue_id),[])
            if len(global_scores)<f['cold_start_min_prior_matches']:
                par=None
            else:
                global_mean=float(np.mean(global_scores))
                strength=f['historical_par_prior_matches']
                class_par=(sum(cl)+strength*global_mean)/(len(cl)+strength)
                par=(sum(ve)+strength*class_par)/(len(ve)+strength)
            par_records.append(dict(match_id=row.match_id,par_score=par,par_prior_matches=len(global_scores),par_class_prior_matches=len(cl),par_venue_prior_matches=len(ve),par_latest_training_date=max((x['date'] for x in []),default=None)))
        for row in daily.itertuples():
            global_scores.append(row.first_total)
            class_scores.setdefault(row.competition_class,[]).append(row.first_total)
            venue_scores.setdefault((row.competition_class,row.venue_id),[]).append(row.first_total)
    par=pd.DataFrame(par_records).drop(columns='par_latest_training_date')
    dates=hist.groupby('match_date').size().index.tolist()
    prior_date={d:dates[i-1] if i else None for i,d in enumerate(dates)}
    par=par.merge(hist[['match_id','match_date']],on='match_id',validate='one_to_one')
    par['par_latest_training_date']=par.match_date.map(prior_date)
    b=b.merge(par.drop(columns='match_date'),on='match_id',validate='many_to_one')
    b=b.merge(m[['match_id','knock_out']],on='match_id',validate='many_to_one')
    b['context_ready']=b.par_score.notna()
    # Stabilized current scoring pace; no current/future delivery outcomes used.
    pseudo=f['projection_prior_balls']
    b['projected_first_innings_score']=(b.runs_before+pseudo*b.par_score/balls)/(b.legal_balls_before+pseudo)*balls
    b['projection_gap_vs_par']=b.par_score-b.projected_first_innings_score
    b['pace_rate']=b.par_score*bpo/balls
    b.to_parquet(PRO/'features.parquet',index=False)
    csv(par,OUT/'feature_par_provenance.csv')
    checks={
      'candidate_rows_preserved':len(b)==int((all_b.analysis_candidate & all_b.is_regular_innings).sum()),
      'before_runs_identity':bool((b.runs_before+b.total_runs).eq(b.groupby(['match_id','innings']).total_runs.cumsum()).all()),
      'before_wickets_identity':bool((b.wickets_before+b.is_wicket.astype(int)).eq(b.groupby(['match_id','innings']).is_wicket.cumsum()).all()),
      'before_legal_identity':bool((b.legal_balls_before+b.is_legal.astype(int)).eq(b.groupby(['match_id','innings']).is_legal.cumsum()).all()),
      'innings_starts_zero':bool(b.groupby(['match_id','innings']).head(1)[['runs_before','wickets_before','legal_balls_before']].eq(0).all().all()),
      'balls_remaining_positive':bool(b.balls_remaining.between(1,balls).all()),
      'wickets_in_hand_positive':bool(b.wickets_in_hand.between(1,wickets).all()),
      'chase_target_matches_first_total':bool(b.loc[b.innings.eq(2),'target'].eq(b.loc[b.innings.eq(2),'match_id'].map(first)+1).all()),
      'historical_par_strictly_earlier_date':bool(par.loc[par.par_score.notna(),'par_latest_training_date'].lt(par.loc[par.par_score.notna(),'match_date']).all()),
      'historical_par_available':bool(b.context_ready.any()),
      'no_player_exclusions':set(b.striker_id)==set(all_b.loc[all_b.analysis_candidate & all_b.is_regular_innings,'striker_id']),
      'regular_unrevised_innings_only':bool(b.first_innings_limit_balls.eq(balls).all() & b.second_innings_limit_balls.eq(balls).all())}
    gate(checks,OUT/'phase2_checks.json')
    summary=dict(matches=int(b.match_id.nunique()),deliveries=len(b),context_ready_matches=int(b.loc[b.context_ready,'match_id'].nunique()),context_ready_deliveries=int(b.context_ready.sum()),cold_start_matches=par.loc[par.par_score.isna(),'match_id'].tolist(),legal_deliveries=int(b.is_legal.sum()),win_probability='skipped: optional; deadline prioritizes ratings and report')
    dump(OUT/'phase2_summary.json',summary)
    (ROOT/'docs/features.md').write_text('''# Match state (Phase 2)

All states are computed BEFORE each physical delivery. Group cumulative totals subtract the current event. Illegal events update runs/wickets but do not decrement legal balls remaining. Powerplay/middle/death are based on legal-ball ordinal, not physical row count. Ordinary target uses first-innings total + 1.

Par uses strictly earlier-date accepted first-innings scores. Class means shrink toward prior global scores, and class/venue means shrink toward class scores, with configured pseudo-match strength. No same-day or future outcome enters par. Cold-start matches with insufficient previous matches remain in the feature file but context_ready=False excludes them from pressure/rating analysis. This limits historical conclusions for the first few matches; no invented par is assigned.

First-innings projection shrinks current team run pace toward historical par with configured pseudo-balls. Final match totals are used only to set second-innings targets and to train par for later matches, never for the same match's first-innings state. Model all primary classes; no nationality filtering. No optional win-probability model is fitted.

Feature parquet preserves all accepted physical deliveries. Subsequent pressure threshold calibration uses legal events; ratings include runs/valid dismissals from illegal events with discipline-appropriate denominators. All revised/shortened matches were explicitly quarantined, so accepted innings use 120 legal balls. Venue IDs only.
''',encoding='utf-8')
    print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
