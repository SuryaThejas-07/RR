from model_common import *

def main():
    b=pd.read_parquet(PRO/'pressure.parquet');b=b[b.is_legal].copy()
    b['dot']=b.runs.eq(0).astype(float);b['boundary']=(b.is_four|b.is_six).astype(float);b['dismissal']=b.is_wicket.astype(float)
    ids=sorted(b.match_id.unique());n=len(ids);cfg=CFG['secondary_separation']
    rng=np.random.default_rng(CFG['seed']);weights=rng.multinomial(n,np.full(n,1/n),size=cfg['bootstrap_draws'])
    metrics={'runs_per_ball':('runs',1),'strike_rate':('runs',100),'economy':('bowler_runs_conceded',6),'dot_rate':('dot',1),'boundary_rate':('boundary',1),'dismissal_rate':('dismissal',1)}
    records=[];stratum_results={};coverage=[]
    groups=[('pooled',None,None,b)]+[(f'{phase}_innings_{inn}',phase,int(inn),g) for (phase,inn),g in b.groupby(['phase','innings'])]
    for label,phase,inn,g in groups:
        counts=g.groupby(['match_id','high_pressure']).size().unstack(fill_value=0).reindex(index=ids,columns=[False,True],fill_value=0)
        common=counts[False].sum()>0 and counts[True].sum()>0
        coverage.append(dict(stratum=label,ordinary_balls=int(counts[False].sum()),pressure_balls=int(counts[True].sum()),estimable=bool(common)))
        for metric,(column,scale) in metrics.items():
            rec=dict(stratum=label,phase=phase,innings=inn,metric=metric,ordinary_balls=int(counts[False].sum()),pressure_balls=int(counts[True].sum()),estimable=bool(common))
            if not common:
                rec['reason']='No common support: one state has no legal deliveries.';records.append(rec);continue
            sums=g.groupby(['match_id','high_pressure'])[column].sum().unstack(fill_value=0).reindex(index=ids,columns=[False,True],fill_value=0)
            means={flag:float(sums[flag].sum()/counts[flag].sum()) for flag in [False,True]}
            draws={}
            for flag in [False,True]:
                denominator=weights@counts[flag].to_numpy()
                draws[flag]=np.divide(weights@sums[flag].to_numpy(),denominator,out=np.full(len(weights),np.nan),where=denominator>0)
            diff=means[True]-means[False];samples=draws[True]-draws[False]
            if metric.endswith('_rate') and metric!='strike_rate':
                effect=2*(np.arcsin(np.sqrt(means[True]))-np.arcsin(np.sqrt(means[False])));effect_name='Cohen h'
            else:
                var=g.groupby('high_pressure')[column].var();pooled_sd=float(np.sqrt((var[False]+var[True])/2));effect=diff/pooled_sd if pooled_sd>0 else 0.;effect_name='standardized mean difference'
            rec.update(ordinary=means[False]*scale,high_pressure=means[True]*scale,difference=diff*scale,ci_low=float(np.nanquantile(samples,cfg['alpha']/2)*scale),ci_high=float(np.nanquantile(samples,1-cfg['alpha']/2)*scale),valid_bootstrap_draws=int(np.isfinite(samples).sum()),effect_size=float(effect),effect_type=effect_name)
            records.append(rec)
            if label!='pooled':stratum_results[(label,metric)]=(len(g),means,samples,scale)
    result=pd.DataFrame(records);csv(result,OUT/'secondary_separation_by_stratum.csv')
    standardized=[]
    for metric in metrics:
        cells=[r for (label,k),r in stratum_results.items() if k==metric]
        denom=sum(x[0] for x in cells)
        if not denom:continue
        ordinary=sum(x[0]*x[1][False]*x[3] for x in cells)/denom
        pressure=sum(x[0]*x[1][True]*x[3] for x in cells)/denom
        draws=sum(x[0]*x[2]*x[3] for x in cells)/denom
        standardized.append(dict(metric=metric,ordinary_standardized=ordinary,pressure_standardized=pressure,difference=pressure-ordinary,ci_low=float(np.nanquantile(draws,cfg['alpha']/2)),ci_high=float(np.nanquantile(draws,1-cfg['alpha']/2)),valid_bootstrap_draws=int(np.isfinite(draws).sum()),common_support_legal_balls=denom,total_legal_balls=len(b),strata_used=len(cells)))
    csv(pd.DataFrame(standardized),OUT/'secondary_separation_standardized.csv')
    q=pd.read_csv(OUT/'audit/quarantine_by_competition.csv');q=q[q.flag_over_15_percent]
    q_summary=dict(flagged_competitions=len(q),match_count_distribution={str(k):int(v) for k,v in q.matches.value_counts().sort_index().items()},minimum_matches=int(q.matches.min()),maximum_matches=int(q.matches.max()),flagged_total_matches=int(q.matches.sum()),flagged_excluded_matches=int(q.excluded_matches.sum()),flagged_total_deliveries=int(q.deliveries.sum()),flagged_excluded_deliveries=int(q.excluded_deliveries.sum()),flagged_delivery_weighted_loss=float(q.excluded_deliveries.sum()/q.deliveries.sum()),flagged_match_weighted_loss=float(q.excluded_matches.sum()/q.matches.sum()))
    dump(OUT/'audit/quarantine_small_competition_review.json',q_summary)
    dump(OUT/'secondary_separation_coverage.json',coverage)
    lines=['# Secondary separation (declared descriptive analysis)','',
    'Original two-metric gate remains failed; team explicitly approved proceeding with that limitation. No pressure settings or acceptance thresholds changed. Same legal-event labels, 1000 whole-match bootstrap draws and 95% percentile intervals. Cohen h for binary rates; standardized mean difference for runs/economy. No new acceptance gate. All six phase × innings strata included; no-common-support cells remain non-estimable. Direct standardization weights common-support strata by their pooled legal-ball counts and resamples the same matches jointly. Intervals are cluster-robust by match, not independent-ball intervals. Tests are descriptive and multiple comparisons are unadjusted.','',
    'Pressure is situational by construction. Pooled separation is strongest for dismissal risk, modest for dot rate and negligible for boundary rate. Ratings compare players with their own disjoint baselines, so pooled separation is not a prerequisite, but construct validity and confounding remain limitations.','', '## Within-stratum standardized results','']
    for r in standardized:
        verdict='interval spans zero' if r['ci_low']<=0<=r['ci_high'] else 'interval excludes zero'
        lines.append(f"- {r['metric']}: ordinary {r['ordinary_standardized']:.6f}, pressure {r['pressure_standardized']:.6f}; difference {r['difference']:.6f}, 95% match-cluster CI [{r['ci_low']:.6f}, {r['ci_high']:.6f}]; {verdict}. Common-support cells {r['strata_used']}/6, coverage {r['common_support_legal_balls']}/{r['total_legal_balls']} legal balls.")
    lines += ['', 'See secondary_separation_by_stratum.csv for all pooled and six stratum comparisons. If the within-stratum difference reverses or disappears, do not describe the pooled direction as context independent. This secondary analysis does not rescue or retrospectively pass the original effect-size criterion.', '', '## Flagged competition attrition','',json.dumps(q_summary,indent=2)]
    (ROOT/'docs/secondary_separation.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(pd.DataFrame(standardized).to_string(index=False));print(json.dumps(q_summary,indent=2))

if __name__=='__main__':main()
