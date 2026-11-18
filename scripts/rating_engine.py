"""Own-baseline, context-adjusted empirical-Bayes ratings; no availability filtering."""
from model_common import *

METRICS=['runs','wicket','dot','boundary']

def context_expectations(b,discipline):
    r=CFG['ratings'];ids=np.sort(b.match_id.unique());rng=np.random.default_rng(CFG['seed'])
    permutation=rng.permutation(ids);folds={int(mid):int(i%r['folds']) for i,mid in enumerate(permutation)}
    fold=b.match_id.map(folds).to_numpy();basekeys=['competition_class','phase','innings']
    work=b[basekeys+['venue_id','batting_team_id','bowling_team_id','match_id']].copy()
    if discipline=='batter':
        y=np.column_stack([b.runs,(b.is_wicket & b.dismissed_player_id.eq(b.striker_id)).astype(float),(b.batter_ball_faced & b.runs.eq(0)).astype(float),(b.is_four|b.is_six).astype(float)])
        opponent='bowling_team_id'
    else:
        y=np.column_stack([b.bowler_runs_conceded,b.bowler_wicket.astype(float),(b.is_legal & b.bowler_runs_conceded.eq(0)).astype(float),(b.is_four|b.is_six).astype(float)])
        opponent='batting_team_id'
    for j,metric in enumerate(METRICS):work['y_'+metric]=y[:,j]
    prediction=np.zeros_like(y,dtype=float);provenance=[]
    for k in range(r['folds']):
        train=work.loc[fold!=k].copy();test=work.loc[fold==k].copy()
        train_base=np.zeros((len(train),4));test_base=np.zeros((len(test),4))
        for j,metric in enumerate(METRICS):
            target='y_'+metric;global_mean=train[target].mean()
            table=train.groupby(basekeys)[target].agg(['sum','count'])
            table['estimate']=(table['sum']+r['context_prior_events']*global_mean)/(table['count']+r['context_prior_events'])
            train_base[:,j]=train[basekeys].merge(table[['estimate']],on=basekeys,how='left',sort=False).estimate.fillna(global_mean).to_numpy()
            test_base[:,j]=test[basekeys].merge(table[['estimate']],on=basekeys,how='left',sort=False).estimate.fillna(global_mean).to_numpy()
            train['residual']=train[target].to_numpy()-train_base[:,j]
            for keys,strength in [(['competition_class','venue_id'],r['venue_prior_events']),(['competition_class',opponent],r['opposition_prior_events'])]:
                correction=train.groupby(keys).residual.agg(['sum','count'])
                correction['adjust']=correction['sum']/(correction['count']+strength)
                train_adj=train[keys].merge(correction[['adjust']],on=keys,how='left',sort=False).adjust.fillna(0).to_numpy()
                test_adj=test[keys].merge(correction[['adjust']],on=keys,how='left',sort=False).adjust.fillna(0).to_numpy()
                train_base[:,j]+=train_adj;test_base[:,j]+=test_adj
                train['residual']-=train_adj
        test_base[:,0]=np.maximum(test_base[:,0],0)
        test_base[:,1:]=np.clip(test_base[:,1:],0,1)
        prediction[fold==k]=test_base
        provenance.append(dict(discipline=discipline,heldout_fold=k,training_matches=int(train.match_id.nunique()),heldout_matches=int(test.match_id.nunique()),overlapping_matches=len(set(train.match_id)&set(test.match_id))))
    return y,prediction,fold,provenance

def observations(b,discipline,prediction=None,y=None):
    if y is None:
        y,prediction,fold,provenance=context_expectations(b,discipline)
    else:fold=None;provenance=[]
    r=b[['delivery_id','match_id','match_date','season','competition_class','innings','phase','high_pressure']].copy()
    r['player_id']=b.striker_id.to_numpy() if discipline=='batter' else b.bowler_id.to_numpy()
    r['legal']=b.is_legal.astype(float).to_numpy()
    r['denominator']=b.batter_ball_faced.astype(float).to_numpy() if discipline=='batter' else b.is_legal.astype(float).to_numpy()
    for j,metric in enumerate(METRICS):
        r[metric]=y[:,j];r['expected_'+metric]=prediction[:,j];r['residual_'+metric]=y[:,j]-prediction[:,j];r['residual_sq_'+metric]=(y[:,j]-prediction[:,j])**2
    if discipline=='batter':
        # A non-striker run-out is charged to the dismissed player, never to the striker.
        mask=b.is_wicket & b.dismissed_player_id.notna() & b.dismissed_player_id.ne(b.striker_id)
        extra=r.loc[mask].copy();extra['player_id']=b.loc[mask,'dismissed_player_id'].astype(int).to_numpy()
        extra[['legal','denominator']]=0.
        for metric in METRICS:
            extra[metric]=1. if metric=='wicket' else 0.
            extra['expected_'+metric]=0.
            extra['residual_'+metric]=extra[metric]
            extra['residual_sq_'+metric]=extra[metric]**2
        extra['off_strike_dismissal']=True;r['off_strike_dismissal']=False
        r=pd.concat([r,extra],ignore_index=True)
    else:r['off_strike_dismissal']=False
    r['discipline']=discipline
    return r,provenance

def aggregates(obs):
    columns=['legal','denominator']+METRICS+['expected_'+k for k in METRICS]+['residual_'+k for k in METRICS]+['residual_sq_'+k for k in METRICS]
    return obs.groupby(['player_id','match_id','high_pressure'],sort=True)[columns].sum().reset_index()

def pooled_variance_floor(agg):
    # Normalize memory layout before reductions: parquet reload/concat can change
    # pandas block layout and hence floating-point reduction order.
    squared=np.array(agg[['residual_sq_'+k for k in METRICS]].to_numpy(),dtype=np.float64,order='C',copy=True)
    exposure=np.array(agg.denominator.to_numpy(),dtype=np.float64,order='C',copy=True)
    return squared.sum(axis=0)/exposure.sum()

def prepare_players(agg,discipline,player_ids=None,variance_floor=None):
    sign=np.array([1,-1,-1,1]) if discipline=='batter' else np.array([-1,1,1,-1])
    players=[]
    # Pooled residual second moment prevents one-match cluster variances collapsing to zero.
    if variance_floor is None:variance_floor=pooled_variance_floor(agg)
    if player_ids is not None:
        agg=agg[agg.player_id.isin(player_ids)]
    for pid,g in agg.groupby('player_id',sort=True):
        mids=np.sort(g.match_id.unique());state=[];denoms=[];raw=[];legal=[]
        for flag in [False,True]:
            q=g[g.high_pressure.eq(flag)].set_index('match_id').reindex(mids,fill_value=0)
            state.append(q[['residual_'+k for k in METRICS]].to_numpy()*sign)
            denoms.append(q.denominator.to_numpy());legal.append(q.legal.to_numpy());raw.append(q[METRICS].to_numpy())
        denominator=np.array(np.stack(denoms),dtype=np.float64,order='C',copy=True)
        legal=np.array(np.stack(legal),dtype=np.float64,order='C',copy=True)
        signed=np.array(np.stack(state),dtype=np.float64,order='C',copy=True)
        raw=np.array(np.stack(raw),dtype=np.float64,order='C',copy=True)
        total=denominator.sum(axis=1);nmatch=len(mids)
        means=np.divide(signed.sum(axis=1),total[:,None],out=np.zeros((2,4)),where=total[:,None]>0)
        delta=means[1]-means[0]
        influence=np.zeros_like(signed)
        for st in [0,1]:
            if total[st]>0:influence[st]=(signed[st]-denominator[st,:,None]*means[st])/total[st]
        multiplier=nmatch/(nmatch-1) if nmatch>1 else 1
        sampling_var=((influence[1]-influence[0])**2).sum(axis=0)*multiplier
        absolute_var=(influence[1]**2).sum(axis=0)*multiplier
        if (total>0).all():sampling_var=np.maximum(sampling_var,variance_floor*(1/total[0]+1/total[1]))
        if total[1]>0:absolute_var=np.maximum(absolute_var,variance_floor/total[1])
        players.append(dict(player_id=int(pid),mids=mids,denominator=denominator,legal=legal,signed=signed,raw=raw,means=means,delta=delta,variance=sampling_var,absolute_variance=absolute_var,paired=bool((total>0).all()),raw_rates=np.divide(raw.sum(axis=1),total[:,None],out=np.full((2,4),np.nan),where=total[:,None]>0),pressure_balls=int(legal[1].sum()),baseline_balls=int(legal[0].sum()),pressure_matches=int((denominator[1]>0).sum()),baseline_matches=int((denominator[0]>0).sum())))
    return players

def hyperparameters(players):
    r=CFG['ratings'];paired=[x for x in players if x['paired']]
    # All paired players enter population estimation, before eligibility/exclusions.
    delta=np.array([x['delta'] for x in paired]);variance=np.array([x['variance'] for x in paired])
    absolute=np.array([x['means'][1] for x in paired]);abs_variance=np.array([x['absolute_variance'] for x in paired])
    tau=np.maximum(np.var(delta,axis=0,ddof=1)-np.mean(variance,axis=0),r['epsilon'])
    abs_tau=np.maximum(np.var(absolute,axis=0,ddof=1)-np.mean(abs_variance,axis=0),r['epsilon'])
    # Zero-gain prior centers remain zero; do not treat a population-wide pressure shift as individual resilience.
    scale=np.sqrt(tau);abs_scale=np.sqrt(abs_tau)
    return dict(tau=tau,absolute_tau=abs_tau,scale=scale,absolute_scale=abs_scale,paired_players=len(paired))

def eligibility(row,minimums=None):
    r=CFG['ratings'];v=minimums or {'pressure':r['min_pressure_balls'],'baseline':r['min_baseline_balls'],'matches':r['min_pressure_matches']}
    return row['pressure_balls']>=v['pressure'] and row['baseline_balls']>=v['baseline'] and row['pressure_matches']>=v['matches'] and row['baseline_matches']>=v['matches']

def point_rating(player,hyp,component_weights=None):
    r=CFG['ratings'];weights=np.array([ (component_weights or r['component_weights'])[k] for k in METRICS]);weights=weights/weights.sum()
    shrink=hyp['tau']/(hyp['tau']+player['variance']);ashrink=hyp['absolute_tau']/(hyp['absolute_tau']+player['absolute_variance'])
    gain=(player['delta']*shrink/hyp['scale'])@weights
    absolute=(player['means'][1]*ashrink/hyp['absolute_scale'])@weights
    # Fixed baseline compare across pressure-match context-residual composites.
    n=player['denominator'][1];means=np.divide(player['signed'][1],n[:,None],out=np.zeros_like(player['signed'][1]),where=n[:,None]>0)
    winner=((means-player['means'][0])/hyp['scale'])@weights>0
    consistency=(winner[n>0].sum()+r['consistency_prior_matches']*.5)/((n>0).sum()+r['consistency_prior_matches'])
    latent=r['delta_weight']*gain+r['absolute_pressure_weight']*absolute+r['consistency_weight']*(2*consistency-1)
    return float(r['rating_center']+r['rating_scale']*latent),shrink,ashrink,float(consistency),float(gain),float(absolute)

def bootstrap(player,hyp,draws,rng,weights=None):
    r=CFG['ratings'];component=np.array([(weights or r['component_weights'])[k] for k in METRICS]);component/=component.sum()
    nmatch=len(player['mids']);multiplicities=rng.multinomial(nmatch,np.full(nmatch,1/nmatch),size=draws)
    means=[];den=[]
    for st in [0,1]:
        d=multiplicities@player['denominator'][st];den.append(d)
        means.append(np.divide(multiplicities@player['signed'][st],d[:,None],out=np.full((draws,4),np.nan),where=d[:,None]>0))
    means=np.stack(means);delta=means[1]-means[0]
    shrink=hyp['tau']/(hyp['tau']+player['variance']);ashrink=hyp['absolute_tau']/(hyp['absolute_tau']+player['absolute_variance'])
    gain=(delta*shrink/hyp['scale'])@component;absolute=(means[1]*ashrink/hyp['absolute_scale'])@component
    match_n=player['denominator'][1];match_means=np.divide(player['signed'][1],match_n[:,None],out=np.zeros_like(player['signed'][1]),where=match_n[:,None]>0)
    wins=(((match_means-means[0,:,None,:])/hyp['scale'])@component>0)&(match_n[None,:]>0)
    # multiplicities weight both wins and eligible pressure-match appearances.
    win_count=(multiplicities*wins).sum(axis=1);count=multiplicities@(match_n>0)
    consistency=(win_count+r['consistency_prior_matches']*.5)/(count+r['consistency_prior_matches'])
    latent=r['delta_weight']*gain+r['absolute_pressure_weight']*absolute+r['consistency_weight']*(2*consistency-1)
    return r['rating_center']+r['rating_scale']*latent

def fit_scope(obs,discipline,scope,intervals=True,component_weights=None):
    r=CFG['ratings'];subset=obs if scope=='Combined' else obs[obs.competition_class.eq(scope)]
    agg=aggregates(subset);players=prepare_players(agg,discipline);hyp=hyperparameters(players)
    rng=np.random.default_rng(CFG['seed']);records=[];boot={}
    for p in players:
        if p['paired']:
            rating,shrink,ashrink,consistency,gain,absolute=point_rating(p,hyp,component_weights)
        else:
            # A missing pressure/ordinary sample is not a zero-performance baseline.
            rating=consistency=gain=absolute=np.nan
            shrink=ashrink=np.full(len(METRICS),np.nan)
        row=dict(player_id=p['player_id'],discipline=discipline,scope=scope,rating=rating,pressure_balls=p['pressure_balls'],baseline_balls=p['baseline_balls'],pressure_matches=p['pressure_matches'],baseline_matches=p['baseline_matches'],eligible=eligibility(p) and p['paired'],paired=p['paired'],match_consistency=consistency,delta_component=gain,absolute_pressure_component=absolute)
        row['rating_status']='estimated_from_disjoint_samples' if p['paired'] else 'unavailable_missing_pressure_or_baseline_exposure'
        for j,k in enumerate(METRICS):
            row['baseline_'+k+'_rate']=p['raw_rates'][0,j];row['pressure_'+k+'_rate']=p['raw_rates'][1,j]
            row['signed_adjusted_delta_'+k]=p['delta'][j] if p['paired'] else np.nan;row['shrinkage_'+k]=shrink[j];row['adjusted_pressure_'+k]=p['means'][1,j] if p['paired'] else np.nan
        row['baseline_metric']=p['raw_rates'][0,0]*(100 if discipline=='batter' else 6)
        row['pressure_metric']=p['raw_rates'][1,0]*(100 if discipline=='batter' else 6)
        row['runs_above_expected_pressure']=float(p['signed'][1,:,0].sum())
        row['wickets_above_expected_pressure']=float(p['signed'][1,:,1].sum())
        if intervals and row['eligible']:
            values=bootstrap(p,hyp,r['bootstrap_draws'],rng,component_weights)
            boot[p['player_id']]=values
            row['ci_low']=float(np.nanquantile(values,r['alpha']/2));row['ci_high']=float(np.nanquantile(values,1-r['alpha']/2));row['bootstrap_valid_draws']=int(np.isfinite(values).sum())
        records.append(row)
    frame=pd.DataFrame(records)
    frame['unfiltered_rank']=pd.Series(pd.NA,index=frame.index,dtype='Int64')
    eligible=frame[frame.eligible].sort_values(['rating','player_id'],ascending=[False,True])
    frame.loc[eligible.index,'unfiltered_rank']=np.arange(1,len(eligible)+1)
    return frame,hyp,boot,players
