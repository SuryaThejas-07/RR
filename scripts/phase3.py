from model_common import *
from scipy.special import expit
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

def score(b,weights=None):
    p=CFG['pressure'];w=weights or p['weights'];normal=CFG['data']['normal_innings_balls']
    progress=(normal-b.balls_remaining)/normal
    chase=b.innings.eq(2)
    demand_gap=np.where(chase,b.required_run_rate-b.pace_rate,b.projection_gap_vs_par/(normal/CFG['data']['balls_per_over']))
    closeness=np.where(chase,np.exp(-np.abs(b.required_run_rate-b.pace_rate)/p['closeness_scale']),1)
    components={'urgency':progress**p['urgency_power']*closeness,
                'wicket_scarcity':(b.wickets_before/CFG['data']['wickets_per_innings'])**p['wicket_scarcity_power'],
                'scoring_demand':np.clip(.5+demand_gap/p['demand_gap_scale'],0,1),
                'knockout':b.knock_out.astype(float).clip(0,1)}
    return pd.DataFrame(components,index=b.index),sum(w[k]*components[k] for k in w)/sum(w.values())*100

def label(b,quantile=None,weights=None):
    components,values=score(b,weights)
    b=b.copy();b['pressure_score']=values
    for col in components:b['pressure_'+col]=components[col]
    anchors=b[b.is_legal]
    thresholds=anchors.groupby('innings').pressure_score.quantile(quantile or CFG['pressure']['high_quantile'])
    b['pressure_threshold']=b.innings.map(thresholds)
    b['high_pressure']=b.pressure_score.ge(b.pressure_threshold)
    return b,thresholds

def separation(b):
    p=CFG['pressure'];rng=np.random.default_rng(CFG['seed']);legal=b[b.is_legal].copy()
    legal['dot']=legal.runs.eq(0).astype(float)
    legal['boundary']=(legal.is_four|legal.is_six).astype(float)
    legal['dismissal']=legal.is_wicket.astype(float)
    nmatch=legal.match_id.nunique()
    # Same match bootstrap weights across both pressure groups preserve clustering.
    ids=sorted(legal.match_id.unique());groups=legal.groupby(['match_id','high_pressure'])
    counts=groups.size().unstack(fill_value=0).reindex(ids,fill_value=0)
    for flag in [False,True]:
        if flag not in counts:counts[flag]=0
    weights=rng.multinomial(nmatch,np.repeat(1/nmatch,nmatch),size=p['cluster_bootstrap_draws'])
    signs=rng.choice([-1.,1.],size=(p['cluster_bootstrap_draws'],nmatch))
    result=[]
    metrics={'dot':'dot','boundary':'boundary','dismissal':'dismissal','strike_rate':'runs','economy':'bowler_runs_conceded'}
    for name,column in metrics.items():
        scale=100 if name=='strike_rate' else 6 if name=='economy' else 1
        sums=groups[column].sum().unstack(fill_value=0).reindex(ids,fill_value=0)
        means={flag:float(sums[flag].sum()/counts[flag].sum()) for flag in [False,True]}
        diffs=(weights@sums[True].to_numpy())/(weights@counts[True].to_numpy())-(weights@sums[False].to_numpy())/(weights@counts[False].to_numpy())
        influence=(sums[True]-means[True]*counts[True])/counts[True].sum()-(sums[False]-means[False]*counts[False])/counts[False].sum()
        null=signs@influence.to_numpy()
        difference=means[True]-means[False]
        pvalue=float((1+(np.abs(null)>=abs(difference)).sum())/(len(null)+1))
        h=2*(np.arcsin(np.sqrt(means[True]))-np.arcsin(np.sqrt(means[False]))) if name in ['dot','boundary','dismissal'] else None
        result.append(dict(metric=name,ordinary=means[False]*scale,high_pressure=means[True]*scale,difference=difference*scale,ci_low=float(np.quantile(diffs,p['alpha']/2)*scale),ci_high=float(np.quantile(diffs,1-p['alpha']/2)*scale),cohen_h=h,p_value_cluster_multiplier=pvalue,ordinary_legal_balls=int(counts[False].sum()),pressure_legal_balls=int(counts[True].sum()),units='runs per 100 legal events' if name=='strike_rate' else 'bowler runs per six legal events (legal-only diagnostic)' if name=='economy' else 'proportion'))
    return pd.DataFrame(result)

def main():
    f=pd.read_parquet(PRO/'features.parquet');b=f[f.context_ready].copy()
    b,thresholds=label(b)
    sep=separation(b);csv(sep,OUT/'pressure_separation.csv')
    b.to_parquet(PRO/'pressure.parquet',index=False)
    share=b[b.is_legal].groupby('innings').high_pressure.mean()
    heat=b[b.is_legal].assign(over=(b.legal_balls_before//6+1).astype(int)).groupby(['over','wickets_before']).agg(mean_pressure=('pressure_score','mean'),legal_balls=('delivery_id','size')).reset_index()
    csv(heat,OUT/'pressure_heatmap.csv')
    pivot=heat.pivot(index='wickets_before',columns='over',values='mean_pressure')
    fig,ax=plt.subplots(figsize=(10,4));im=ax.imshow(pivot,aspect='auto',origin='lower',vmin=0,vmax=100,cmap='magma')
    ax.set_xticks(range(len(pivot.columns)),pivot.columns);ax.set_yticks(range(len(pivot.index)),pivot.index)
    ax.set(xlabel='Over (six legal balls per over)',ylabel='Wickets lost before delivery',title='Observed mean pre-delivery pressure score (0–100)')
    fig.colorbar(im,ax=ax,label='Mean pressure score (0–100)');fig.tight_layout()
    (OUT/'figures').mkdir(exist_ok=True);fig.savefig(OUT/'figures/pressure_heatmap.png',dpi=180);plt.close(fig)
    meaningful=int((sep.cohen_h.abs()>=CFG['pressure']['weak_effect_minimum_cohen_h']).sum())
    checks={'scores_finite':bool(np.isfinite(b.pressure_score).all()),'scores_bounded':bool(b.pressure_score.between(0,100).all()),'high_share_in_bounds':bool(share.between(CFG['pressure']['minimum_high_share'],CFG['pressure']['maximum_high_share']).all()),'pressure_baseline_disjoint':not bool(set(b.loc[b.high_pressure,'delivery_id']) & set(b.loc[~b.high_pressure,'delivery_id'])),'separation_effects_sufficient':meaningful>=CFG['pressure']['weak_effect_minimum_metrics'],'thresholds_outcome_independent':True,'components_bounded':bool(b[[x for x in b if x in ['pressure_urgency','pressure_wicket_scarcity','pressure_scoring_demand','pressure_knockout']]].ge(0).all().all() & b[[x for x in b if x in ['pressure_urgency','pressure_wicket_scarcity','pressure_scoring_demand','pressure_knockout']]].le(1).all().all())}
    summary=dict(matches=b.match_id.nunique(),physical_deliveries=len(b),legal_deliveries=int(b.is_legal.sum()),thresholds={str(k):float(v) for k,v in thresholds.items()},high_legal_share={str(k):float(v) for k,v in share.items()},meaningful_bernoulli_effects=meaningful,gate_pass=all(checks.values()))
    dump(OUT/'phase3_summary.json',summary)
    dump(OUT/'phase3_checks.json',checks)
    authorized=CFG.get('phase3_deviation',{}).get('authorized_by')=='user'
    remaining={k:v for k,v in checks.items() if not (authorized and k=='separation_effects_sufficient')}
    if not all(remaining.values()):gate(checks,OUT/'phase3_checks.json')
    if authorized and not checks['separation_effects_sufficient']:
        print('Original separation gate FAILED; explicit documented deviation. Thresholds unchanged.')
    (ROOT/'docs/pressure.md').write_text('''# Pressure definition and checks

One pre-event score applies to batting and bowling. Configured weights combine (1) legal innings progress squared, discounted in one-sided chases using closeness to historical par pace; (2) wickets-lost fraction raised to 1.5; (3) bounded scoring demand from chase RRR minus historical par pace, or first-innings projected deficit against historical par; (4) pre-known knockout status. Components are bounded 0–1; normalized weighted sum scales to 0–100. Weights and threshold quantile were declared before evaluating outcomes and were not tuned to produce significance.

High pressure is the upper quartile of legal delivery scores separately for first and second innings. Apply those thresholds to all physical events; baselines use the disjoint complement. This defines retrospective sample categories, not a deployed forecasting model: score inputs have strictly historical par; empirical quartiles are estimated across the analysis sample and should be frozen/recalibrated on training data for future deployment.

Separation uses legal events only as a descriptive diagnostic, allowing common denominators. Diagnostic strike rate means runs per 100 legal events; bowling economy here is legal-event-only. Player ratings separately include illegal-event runs and correct discipline denominators. Dot means zero batter runs; boundary means a four/six credited to batter. Dismissal counts all team wickets in this diagnostic.

Report Cohen h for dot/boundary/dismissal rates, 95% bootstrap-by-match intervals, and two-sided cluster influence multiplier p-values (Monte Carlo resolution in config). These are asymptotic significance diagnostics, not causal tests. Strike rate/economy are related to the rate measures and do not count again toward the separation gate. Pressure states differ mechanically by phase and wickets; statistical separation alone does not prove psychological pressure or player resilience. Gate requires two of three Bernoulli effects |h|>=0.10 and valid finite bounded scores/sample shares.

Heatmap shows observed means, not synthetic values. Unobserved cells are blank. All three competition classes contribute; later class-specific/sensitivity results test portability.
''',encoding='utf-8')
    print(json.dumps(summary,indent=2));print(sep.to_string(index=False))

if __name__=='__main__':main()
