"""Phase 5: conditional repeatability, sensitivity, placebo and rank uncertainty."""
from model_common import *
from rating_engine import METRICS,aggregates,prepare_players,point_rating,fit_scope,eligibility,hyperparameters,pooled_variance_floor
from phase3 import label
from scipy.stats import spearmanr,kendalltau
import hashlib
import html
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

def hypotheses():
    entries=json.loads((OUT/'eb_hyperparameters.json').read_text())
    return {(x['discipline'],x['scope']):{k:np.array(v) if isinstance(v,list) else v for k,v in x.items() if k not in ['discipline','scope']} for x in entries}

def score_subset(obs,discipline,hyp,allowed=None,minimum=None,variance_floor=None):
    players=prepare_players(aggregates(obs),discipline,player_ids=allowed,variance_floor=variance_floor)
    records=[]
    for player in players:
        if allowed is not None and player['player_id'] not in allowed:continue
        if minimum is not None and (player['pressure_balls']<minimum or player['baseline_balls']<minimum):continue
        if not player['paired']:continue
        value=point_rating(player,hyp)[0]
        records.append(dict(player_id=player['player_id'],rating=value,pressure_balls=player['pressure_balls'],baseline_balls=player['baseline_balls']))
    return pd.DataFrame(records,columns=['player_id','rating','pressure_balls','baseline_balls'])

def compare(base,alternative):
    base=base.sort_values(['rating','player_id'],ascending=[False,True])
    alternative=alternative.sort_values(['rating','player_id'],ascending=[False,True])
    common=base[['player_id','rating']].merge(alternative[['player_id','rating']],on='player_id',suffixes=('_base','_alternative'))
    bt=set(base.head(10).player_id);at=set(alternative.head(10).player_id)
    tau=float(kendalltau(common.rating_base,common.rating_alternative).statistic) if len(common)>1 else None
    return dict(common_players=len(common),base_eligible=len(base),alternative_eligible=len(alternative),top10_overlap=len(bt&at),top10_overlap_denominator=min(10,len(bt),len(at)),kendall_tau_common=tau)

def rank_uncertainty(ratings):
    frames=[]
    for (scope,discipline),group in ratings[ratings.eligible].groupby(['scope','discipline']):
        bundle=np.load(OUT/f'bootstrap_{discipline}_{scope}.npz')
        ids=bundle['player_ids'];values=bundle['ratings']
        order=np.argsort(-np.nan_to_num(values,nan=-np.inf),axis=0,kind='stable')
        ranks=np.empty_like(order)
        np.put_along_axis(ranks,order,np.broadcast_to(np.arange(1,len(ids)+1)[:,None],order.shape),axis=0)
        alpha=CFG['ratings']['alpha']
        rankstats=pd.DataFrame(dict(player_id=ids,rank_ci_low=np.quantile(ranks,alpha/2,axis=1),rank_ci_high=np.quantile(ranks,1-alpha/2,axis=1),bootstrap_top10_probability=(ranks<=10).mean(axis=1),rank_complete_draws=np.isfinite(values).sum(axis=1)))
        group=group.merge(rankstats,on='player_id',validate='one_to_one')
        group['neutral_score_in_interval']=group.ci_low.le(CFG['ratings']['rating_center']) & group.ci_high.ge(CFG['ratings']['rating_center'])
        group['wide_rank_interval']=(group.rank_ci_high-group.rank_ci_low)>CFG['validation']['fragile_rank_width']
        group['low_top10_probability']=group.unfiltered_rank.le(10)&group.bootstrap_top10_probability.lt(CFG['validation']['fragile_top10_probability'])
        group['fragile_rank']=group[['neutral_score_in_interval','wide_rank_interval','low_top10_probability']].any(axis=1)
        group['fragile_reasons']=group.apply(lambda r:';'.join(k for k in ['neutral_score_in_interval','wide_rank_interval','low_top10_probability'] if r[k]),axis=1)
        frames.append(group)
    return pd.concat(frames,ignore_index=True)

def reliability(observations,ratings,hyp):
    full=ratings[ratings.scope.eq('Combined') & ratings.eligible]
    ids=np.sort(observations.match_id.unique());rng=np.random.default_rng(CFG['seed']);perm=rng.permutation(ids)
    halfmap={int(mid):i%2 for i,mid in enumerate(perm)}
    all_results=[];pair_records=[]
    for discipline in ['batter','bowler']:
        obs=observations[observations.discipline.eq(discipline)]
        allowed=set(full.loc[full.discipline.eq(discipline),'player_id']);population=hyp[(discipline,'Combined')]
        floor=CFG['validation']['technical_min_balls_per_state']
        halves=[score_subset(obs[obs.match_id.map(halfmap).eq(k)],discipline,population,allowed,floor) for k in [0,1]]
        comparison=halves[0].merge(halves[1],on='player_id',suffixes=('_a','_b'))
        groups=[('random_match_split_half',None,None,comparison)]
        # Original season strings sort by their leading year, then lexical detail.
        seasons=sorted(obs.season.astype(str).unique(),key=lambda x:(int(x[:4]),x))
        for left,right in zip(seasons[:-1],seasons[1:]):
            a=score_subset(obs[obs.season.astype(str).eq(left)],discipline,population,allowed,floor)
            b=score_subset(obs[obs.season.astype(str).eq(right)],discipline,population,allowed,floor)
            groups.append(('adjacent_seasons',left,right,a.merge(b,on='player_id',suffixes=('_a','_b'))))
        # Calendar-year aggregation is an additional explicit diagnostic to avoid interpreting tiny cross-year season labels as independent full seasons.
        years=sorted(obs.match_date.str[:4].unique())
        for left,right in zip(years[:-1],years[1:]):
            a=score_subset(obs[obs.match_date.str[:4].eq(left)],discipline,population,allowed,floor)
            b=score_subset(obs[obs.match_date.str[:4].eq(right)],discipline,population,allowed,floor)
            groups.append(('adjacent_calendar_years',left,right,a.merge(b,on='player_id',suffixes=('_a','_b'))))
        for test,left,right,pairs in groups:
            count=len(pairs)
            valid=count>=3 and pairs.rating_a.nunique()>1 and pairs.rating_b.nunique()>1
            record=dict(discipline=discipline,test=test,period_a=left,period_b=right,paired_players=count,eligible_full_sample=len(allowed),technical_min_balls_per_state=floor,estimable=valid,spearman_rho=float(spearmanr(pairs.rating_a,pairs.rating_b).statistic) if valid else None,kendall_tau=float(kendalltau(pairs.rating_a,pairs.rating_b).statistic) if valid else None)
            all_results.append(record)
            for row in pairs.to_dict('records'):pair_records.append(dict(discipline=discipline,test=test,period_a=left,period_b=right,**row))
    return pd.DataFrame(all_results),pd.DataFrame(pair_records)

def sensitivity(observations,ratings,hyp):
    results=[];scenario_ranks=[]
    combined=ratings[ratings.scope.eq('Combined') & ratings.eligible]
    # Frozen original component weights, pressure settings and eligibility remain authoritative.
    for discipline in ['batter','bowler']:
        obs=observations[observations.discipline.eq(discipline)]
        base=combined[combined.discipline.eq(discipline)]
        population=hyp[(discipline,'Combined')]
        players=prepare_players(aggregates(obs),discipline)
        def save(name,alternative):
            result=compare(base,alternative);results.append(dict(discipline=discipline,scenario=name,**result))
            alternative=alternative.sort_values(['rating','player_id'],ascending=[False,True]).copy()
            alternative['rank']=np.arange(1,len(alternative)+1)
            scenario_ranks.extend({**row,'discipline':discipline,'scenario':name} for row in alternative.to_dict('records'))
        for metric in METRICS:
            for direction in [-1,1]:
                weights=CFG['ratings']['component_weights'].copy();weights[metric]*=1+direction*CFG['validation']['weight_perturbation']
                alternative=pd.DataFrame([dict(player_id=p['player_id'],rating=point_rating(p,population,weights)[0]) for p in players if eligibility(p) and p['paired']])
                save(f'component_{metric}_{direction:+d}20pct',alternative)
        for minimums in CFG['validation']['sensitivity_eligibility']:
            alternative=pd.DataFrame([dict(player_id=p['player_id'],rating=point_rating(p,population)[0]) for p in players if eligibility(p,minimums) and p['paired']])
            save('eligibility_'+str(minimums['pressure']),alternative)
        # Change only retrospective high-pressure cutoff for sensitivity; held-out context expectations stay frozen.
        features=pd.read_parquet(PRO/'pressure.parquet')
        for q in CFG['validation']['sensitivity_quantiles']:
            labelled,_=label(features,quantile=q)
            alternative_obs=obs.copy();alternative_obs['high_pressure']=alternative_obs.delivery_id.map(labelled.set_index('delivery_id').high_pressure)
            frame,_,_,_=fit_scope(alternative_obs,discipline,'Combined',intervals=False)
            save(f'pressure_quantile_{q:.2f}',frame[frame.eligible])
    return pd.DataFrame(results),pd.DataFrame(scenario_ranks)

def placebo(observations,ratings,hyp):
    b=pd.read_parquet(PRO/'pressure.parquet')
    rng=np.random.default_rng(CFG['seed']);reps=CFG['validation']['placebo_repetitions']
    # Freeze full-sample eligible identities so the placebo does not change the target population.
    full=ratings[ratings.scope.eq('Combined') & ratings.eligible]
    # Group indices for within-match/innings/phase permutation, including illegal events.
    groups=list(b.groupby(['match_id','innings','phase'],sort=True).indices.values())
    original=b.high_pressure.to_numpy();ids=b.delivery_id.to_numpy()
    eligible_observations={d:observations[observations.discipline.eq(d)&observations.player_id.isin(full.loc[full.discipline.eq(d),'player_id'])].copy() for d in ['batter','bowler']}
    fixed_floor={d:pooled_variance_floor(aggregates(observations[observations.discipline.eq(d)])) for d in ['batter','bowler']}
    output=[]
    for repetition in range(reps):
        shuffled=original.copy()
        for positions in groups:shuffled[positions]=rng.permutation(original[positions])
        labels=pd.Series(shuffled,index=ids)
        for discipline in ['batter','bowler']:
            obs=eligible_observations[discipline].copy();obs['high_pressure']=obs.delivery_id.map(labels)
            alternative=score_subset(obs,discipline,hyp[(discipline,'Combined')],variance_floor=fixed_floor[discipline])
            actual=full[full.discipline.eq(discipline)]
            common=actual[['player_id','rating']].merge(alternative,on='player_id',suffixes=('_actual','_placebo'))
            overlap=len(set(actual.sort_values('rating',ascending=False).head(10).player_id)&set(alternative.sort_values('rating',ascending=False).head(10).player_id))
            output.append(dict(discipline=discipline,repetition=repetition,actual_score_sd=float(actual.rating.std()),placebo_score_sd=float(alternative.rating.std()),top10_overlap=overlap,paired_players=len(common),score_correlation=float(spearmanr(common.rating_actual,common.rating_placebo).statistic) if len(common)>2 else None))
        if (repetition+1)%20==0:print('Placebo repetitions',repetition+1,'/',reps,flush=True)
    return pd.DataFrame(output)

def render_review(top,formats,distribution,reliability_result,sensitivity_result,placebos):
    def table(frame,columns):
        view=frame[columns].copy()
        if 'fragile_rank' in view:view['fragile_rank']=view.fragile_rank.map({True:'Yes',False:'No'})
        if 'fragile_reasons' in view:
            view['fragile_reasons']=view.fragile_reasons.fillna('None').replace('', 'None').str.replace('neutral_score_in_interval','score CI includes neutral 50',regex=False).str.replace('wide_rank_interval','rank interval spans >10 places',regex=False).str.replace('low_top10_probability','top-10 probability below 50%',regex=False).str.replace(';','; ',regex=False)
        for column in view.select_dtypes(include=['float','float64']):view[column]=view[column].map(lambda x:'' if pd.isna(x) else f'{x:.2f}')
        return view.to_html(index=False,escape=True,border=0,na_rep='Unavailable')
    columns=['unfiltered_rank','display_name','pressure_balls','pressure_matches','baseline_balls','rating','ci_low','ci_high','rank_ci_low','rank_ci_high','bootstrap_top10_probability','fragile_rank','fragile_reasons','nationality_flag']
    sections=['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>RR Phase 5 review</title><style>body{font:15px/1.5 system-ui,sans-serif;color:#0b1b3f;margin:36px auto;max-width:1500px;padding:0 24px}h1{font-size:30px}h2{margin-top:36px;font-size:22px}h3{font-size:18px}table{border-collapse:collapse;width:100%;font-size:12px;font-variant-numeric:tabular-nums}th,td{padding:8px;text-align:left;border-bottom:1px solid #ddd;vertical-align:top}th{background:#edf0f5}td:nth-child(2){font-weight:600}.scroll{overflow:auto}p{max-width:1100px}.warning{padding:16px;border-left:4px solid #ea1a85;background:#fcf0f6}img{max-width:100%}@media print{body{margin:0;font-size:10px}h2{break-before:page}table{font-size:8px}th,td{padding:4px}.scroll{overflow:visible}}</style><h1>Pressure reliability: Phase 5 review</h1>',
    '<p class="warning">UNFILTERED RESEARCH RANKINGS — not final auction recommendations. Pakistan/Bangladesh flags are shown, not removed here. Contract, RR membership, retirement and unknown-nationality review remain for Phase 6. All settings fixed; T20I batting has only four qualified players by explicit user authorization.</p>',
    '<p>Pressure is situational by construction. The original two-metric effect-size criterion failed; only dismissal passed. Secondary phase × innings standardized intervals all span zero. Own-baseline ratings do not rely on pooled separation but remain observational. 95% score/rank intervals are conditional on fixed context/EB fits, with independent per-player match resamples for approximate rank uncertainty. The rating is an index (50 = neutral), not probability. Fragility flags identify neutral-score intervals, rank width >10, or point top-10 probability <50%.</p>']
    for discipline in ['batter','bowler']:
        sections+=['<h2>Combined unfiltered top 15 '+discipline+'s</h2><div class="scroll">',table(top[top.discipline.eq(discipline)].sort_values('unfiltered_rank'),columns),'</div>']
    for scope in ['IPL','T20I']:
        for discipline in ['batter','bowler']:
            frame=formats[formats.scope.eq(scope)&formats.discipline.eq(discipline)].sort_values('unfiltered_rank')
            title=f'{scope}-only {discipline}s — '+('four qualified players; no padding' if len(frame)<10 else 'top 10')
            sections+=['<h2>'+title+'</h2><div class="scroll">',table(frame,columns),'</div>']
    sections+=['<h2>Eligible pressure-ball distributions</h2><p>Exposure cutoffs: 200 pressure / 400 ordinary legal balls, ten matches per state, unchanged. Histogram covers every eligible Combined player, including national-team flags.</p><img src="figures/eligible_pressure_balls.png" alt="Pressure legal-ball counts among eligible players"><div class="scroll">',table(distribution,list(distribution.columns)),'</div>',
    '<h2>Repeatability</h2><p>Frozen held-out residuals and full-sample population scales; subset floor 20 legal balls per state. This is conditional repeatability, not a refitted independent future-prediction test. Small/non-estimable pairs are explicit.</p><div class="scroll">',table(reliability_result,list(reliability_result.columns)),'</div>',
    '<h2>Sensitivity</h2><p>Declared diagnostic alternatives; principal settings unchanged. Top-10 overlap is out of ten unless fewer qualify. Kendall tau uses common eligible identities.</p><div class="scroll">',table(sensitivity_result,list(sensitivity_result.columns)),'</div>',
    '<h2>Placebo</h2><p>100 label permutations within match × innings × phase; preserves context composition. Original eligible identities and nuisance fits held fixed. This tests sensitivity to the situational labelling, not causality. Lack of distinction from placebo is a limitation.</p><div class="scroll">',table(placebos.groupby('discipline')[['actual_score_sd','placebo_score_sd','top10_overlap','score_correlation']].mean().reset_index(),['discipline','actual_score_sd','placebo_score_sd','top10_overlap','score_correlation']),'</div></html>']
    (OUT/'phase5_review.html').write_text('\n'.join(sections),encoding='utf-8')

def main():
    obs=pd.read_parquet(PRO/'rating_observations.parquet');ratings=pd.read_parquet(PRO/'ratings.parquet');hyp=hypotheses()
    print('Calculating rank uncertainty',flush=True)
    ranked=rank_uncertainty(ratings)
    ranked['permanent_nationality_exclusion']=ranked.nationality_flag.isin(['Pakistan','Bangladesh'])
    ranked['availability_note']='Unfiltered research list; contract/retirement/unknown review not applied'
    csv(ranked,OUT/'eligible_ratings_with_validation.csv')
    top=ranked[ranked.scope.eq('Combined') & ranked.unfiltered_rank.le(15)].sort_values(['discipline','unfiltered_rank'])
    formats=ranked[ranked.scope.isin(['IPL','T20I']) & ranked.unfiltered_rank.le(10)].sort_values(['scope','discipline','unfiltered_rank'])
    csv(top,OUT/'unfiltered_top15_phase5.csv');csv(top,OUT/'rankings_all_players.csv');csv(formats,OUT/'format_top10_phase5.csv')
    csv(ranked[ranked.fragile_rank],OUT/'fragile_ranks.csv')
    print('Calculating split-half and seasonal reliability',flush=True)
    rel,pairs=reliability(obs,ratings,hyp);csv(rel,OUT/'reliability_summary.csv');csv(pairs,OUT/'reliability_player_pairs.csv')
    print('Calculating declared sensitivity scenarios',flush=True)
    sens,scenario_ranks=sensitivity(obs,ratings,hyp);csv(sens,OUT/'sensitivity_summary.csv');csv(scenario_ranks,OUT/'sensitivity_player_ranks.csv')
    print('Calculating contextual placebo',flush=True)
    plac=placebo(obs,ratings,hyp);csv(plac,OUT/'placebo_results.csv')
    distribution=pd.read_csv(OUT/'eligible_pressure_ball_distribution.csv')
    columns=['scope','discipline','player_id','display_name','pressure_balls','baseline_balls','pressure_matches','baseline_matches']
    csv(ranked[columns].sort_values(['scope','discipline','pressure_balls','player_id']),OUT/'eligible_pressure_ball_counts.csv')
    (OUT/'figures').mkdir(exist_ok=True)
    fig,axes=plt.subplots(1,2,figsize=(11,4),sharey=False)
    for ax,discipline in zip(axes,['batter','bowler']):
        group=ranked[ranked.scope.eq('Combined')&ranked.discipline.eq(discipline)]
        ax.hist(group.pressure_balls,bins='auto',color='#EA1A85' if discipline=='batter' else '#0B1B3F',edgecolor='white')
        ax.set(title=f'Combined eligible {discipline}s (n={len(group)})',xlabel='Pressure legal balls per player',ylabel='Number of eligible players')
    fig.tight_layout();fig.savefig(OUT/'figures/eligible_pressure_balls.png',dpi=170);plt.close(fig)
    render_review(top,formats,distribution,rel,sens,plac)
    names=pd.read_parquet(PRO/'players.parquet').set_index('player_id').display_name
    core=ratings[ratings.scope.eq('Combined')]
    # Meaningful reproducibility check: independently rerun point ratings (no bootstrap) and compare every Combined player, before filtering.
    deterministic=[]
    for discipline in ['batter','bowler']:
        again,_,_,_=fit_scope(obs[obs.discipline.eq(discipline)],discipline,'Combined',intervals=False)
        joined=core[core.discipline.eq(discipline)][['player_id','rating']].merge(again[['player_id','rating']],on='player_id',suffixes=('_original','_rerun'))
        deterministic.append(len(joined)==len(again) and np.array_equal(joined.rating_original.to_numpy(),joined.rating_rerun.to_numpy(),equal_nan=True))
    checks={
      'top15_each_discipline_unique':all(len(g)==15 and g.player_id.nunique()==15 for _,g in top.groupby('discipline')),
      'format_capacity_exact_authorized_counts':len(formats[formats.scope.eq('T20I')&formats.discipline.eq('batter')])==4 and all(len(formats[formats.scope.eq(scope)&formats.discipline.eq(discipline)])==10 for scope,discipline in [('IPL','batter'),('IPL','bowler'),('T20I','bowler')]),
      'names_canonical':ranked.display_name.eq(ranked.player_id.map(names)).all(),
      'rank_intervals_ordered':ranked.rank_ci_low.le(ranked.rank_ci_high).all(),
      'top10_probability_bounded':ranked.bootstrap_top10_probability.between(0,1).all(),
      'repeatability_analyses_written':set(rel.test)=={'random_match_split_half','adjacent_seasons','adjacent_calendar_years'},
      'declared_sensitivity_scenarios_complete':sens.groupby('discipline').size().eq(12).all(),
      'placebo_repetitions_complete':plac.groupby('discipline').size().eq(CFG['validation']['placebo_repetitions']).all(),
      'point_ratings_identical_on_rerun':all(deterministic),
      'availability_filter_invariant':all(np.array_equal(core[core.discipline.eq(d)].set_index('player_id').loc[core[core.discipline.eq(d)&~core.nationality_flag.isin(['Pakistan','Bangladesh'])].player_id,'rating'].to_numpy(),core[core.discipline.eq(d)&~core.nationality_flag.isin(['Pakistan','Bangladesh'])].rating.to_numpy(),equal_nan=True) for d in ['batter','bowler']),
      'no_final_ranking_file':not (OUT/'rankings_final.csv').exists(),
      'pressure_gate_failure_preserved':json.loads((OUT/'phase3_checks.json').read_text())['separation_effects_sufficient'] is False}
    gate({k:bool(v) for k,v in checks.items()},OUT/'phase5_checks.json')
    write_summary_and_notes(top,ranked,rel,sens,plac)

def write_summary_and_notes(top,ranked,rel,sens,plac):
    summary={'split_half':rel[rel.test.eq('random_match_split_half')].astype(object).where(lambda frame:frame.notna(),None).to_dict('records'),
      'fragile_combined_top15':{d:int(top.loc[top.discipline.eq(d),'fragile_rank'].sum()) for d in ['batter','bowler']},
      'sensitivity_range':sens.groupby('discipline').agg(min_overlap=('top10_overlap','min'),max_overlap=('top10_overlap','max'),min_tau=('kendall_tau_common','min'),max_tau=('kendall_tau_common','max')).reset_index().to_dict('records'),
      'placebo_summary':plac.groupby('discipline').agg(actual_score_sd=('actual_score_sd','first'),mean_placebo_score_sd=('placebo_score_sd','mean'),mean_top10_overlap=('top10_overlap','mean'),mean_score_correlation=('score_correlation','mean')).reset_index().to_dict('records'),
      'combined_eligible_counts':ranked[ranked.scope.eq('Combined')].groupby('discipline').size().to_dict(),
      't20i_batting_count':4,'pressure_gate_deviation':True,'capacity_deviation':True}
    dump(OUT/'phase5_summary.json',summary)
    text=['# Phase 5 validation findings','',
      'UNFILTERED RESEARCH RANKINGS, not final auction picks. Phase 3 original separation gate remains failed by explicit documented deviation. T20I batting has four qualified players by explicit authorization; no thresholds changed.','',
      '## Reliability and limits','',
      'Frozen held-out context predictions and full-sample EB scales make these conditional repeatability diagnostics. Split-half is random by entire match, not by ball. Adjacent original seasons and calendar years are reported with the 20-ball-per-state technical floor and original full-sample eligible cohort. Non-estimable/small pairs are explicit. These are not independently refitted or prospective holdout scores.','']
    text += [f"- {r['discipline']} split-half: Spearman {r['spearman_rho']:.4f}, Kendall {r['kendall_tau']:.4f}; {r['paired_players']} paired players." for r in summary['split_half']]
    text += ['', '## Rank uncertainty','',
      'Score CIs are 95% match-bootstrap intervals conditional on fitted context/EB parameters. Saved player resamples are independent across players and omit shared-match covariance; rank intervals and top-10 probabilities are approximate diagnostics. A neutral score of 50 lies in many intervals. Fragility flags use only the predeclared criteria; they do not prove underperformance.',
      f"Combined top-15 fragile counts: {summary['fragile_combined_top15']}. A rank should not be read as a statistically separated ordering when intervals overlap.",'','## Sensitivity and placebo','',
      'Weights, pressure quantiles and eligibility alternatives were declared before scoring. Principal settings are unchanged. Common-player Kendall tau and top-10 overlap quantify ordering/population changes. Pressure quantile alternatives refit EB from frozen residuals; weight alternatives freeze EB. Placebo labels are permuted within match × innings × phase, preserving phase composition, and scores use frozen context/EB fits and original eligible identities. Placebo does not refit nuisance models and is not a causal test. High real/placebo overlap or similar spread weakens claims of distinctive situational skill.',json.dumps(summary['sensitivity_range'],indent=2),json.dumps(summary['placebo_summary'],indent=2),'',
      '## Outputs','',
      '- outputs/phase5_review.html: full readable top-15 lists, IPL/T20I lists, intervals, fragility and distributions.',
      '- outputs/unfiltered_top15_phase5.csv and rankings_all_players.csv: combined top 15 per discipline with nationality exclusion annotations.',
      '- outputs/format_top10_phase5.csv: unfiltered IPL top 10 and T20I top 10/four qualified batters.',
      '- outputs/eligible_pressure_ball_counts.csv and eligible_pressure_ball_distribution.csv: every eligible exposure and summary distribution.',
      '- reliability_summary.csv, reliability_player_pairs.csv, sensitivity_summary.csv, sensitivity_player_ranks.csv, placebo_results.csv and fragile_ranks.csv: complete diagnostics.',
      '', '## Recruitment and construct limitations','',
      'Pressure is situational by construction; pooled separation is strongest for dismissal risk, modest for dots and negligible for boundaries. The original two-metric effect-size gate failed. Phase/innings standardization has wide intervals spanning zero, including sparse powerplay support. Own-baseline ratings do not rely on pooled separation but remain observational and sensitive to sample, context/EB estimates, player roles and scoring choices. The unfiltered lists include permanently excluded Pakistan/Bangladesh flags for audit; final availability, retained squads, retirement and top-40 unknown-nationality review are deferred to Phase 6. No auction prices, current squad assertions or verified availability are inferred.']
    (ROOT/'docs/validation.md').write_text('\n'.join(text)+'\n',encoding='utf-8')
    print(json.dumps(summary,indent=2));print('Phase 5 computational checks passed; substantive reliability limitations must be reviewed.')

def finish_from_saved():
    checks=json.loads((OUT/'phase5_checks.json').read_text())
    if not all(checks.values()):raise AssertionError('Cannot finish report while Phase 5 checks fail.')
    top=pd.read_csv(OUT/'unfiltered_top15_phase5.csv');ranked=pd.read_csv(OUT/'eligible_ratings_with_validation.csv')
    rel=pd.read_csv(OUT/'reliability_summary.csv');sens=pd.read_csv(OUT/'sensitivity_summary.csv');plac=pd.read_csv(OUT/'placebo_results.csv')
    write_summary_and_notes(top,ranked,rel,sens,plac)

if __name__=='__main__':main()
