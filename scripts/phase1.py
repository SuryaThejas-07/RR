"""Auditable Phase 1 only: profiling, score reconciliation, identity and nationality."""
from pathlib import Path
import hashlib
import importlib.metadata
import json
import re
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.runtime/python'))
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT/'config.yaml').read_text(encoding='utf-8-sig'))
DC = CFG['data']
RAW, PROCESSED, AVAIL, AUDIT = [ROOT/CFG['paths'][x] for x in ['raw','processed','availability','audit']]
for directory in [PROCESSED, AVAIL, AUDIT]:
    directory.mkdir(parents=True,exist_ok=True)

def write_json(path,value):
    path.write_text(json.dumps(value,indent=2,default=str,ensure_ascii=False)+'\n',encoding='utf-8')

def export(df,name,where=AUDIT):
    df.to_csv(where/name,index=False,lineterminator='\n')

def load():
    return {p.stem:pd.read_csv(p,low_memory=False) for p in sorted(RAW.glob('*.csv'))}

def profile(tables):
    results={}
    for name,df in tables.items():
        results[name]={'rows':len(df),'columns':len(df.columns),'exact_duplicate_rows':int(df.duplicated().sum()),'fields':{}}
        for col in df:
            s=df[col]
            results[name]['fields'][col]={'dtype':str(s.dtype),'nulls':int(s.isna().sum()),'null_rate':float(s.isna().mean()),'distinct_non_null':int(s.nunique()),'samples':[str(x) for x in s.dropna().drop_duplicates().head(5)]}
    write_json(AUDIT/'profiles.json',results)
    return results

def score_validation(b,m):
    summaries=[]
    validations={}
    for label,columns in [('runs_only',['runs']),('runs_plus_extras1',['runs','extras1_runs']),('runs_plus_both_extras',['runs','extras1_runs','extras_2_runs'])]:
        totals=b.assign(candidate_total=b[columns].sum(axis=1)).groupby(['match_id','innings']).agg(total=('candidate_total','sum'),wickets=('is_wicket','sum'),team=('batting_team_id','first'))
        records=[]
        for row in m.itertuples():
            get=lambda inn: totals.loc[(row.match_id,inn)] if (row.match_id,inn) in totals.index else None
            a,z=get(1),get(2)
            result=str(row.result)
            explicit_dls=bool(re.search(r'D\s*/\s*L|DLS',result,re.I))
            # Infer target adjustment only with the evidence-supported scoring formula.
            adjusted_target=(label=='runs_plus_both_extras' and a is not None and pd.notna(row.revised_target) and row.revised_target != a.total+1)
            superover=bool(re.search(r'super\s*over|eliminator',result,re.I)) or get(3) is not None
            noresult=bool(re.search(r'no result|abandoned',result,re.I))
            rec=dict(match_id=row.match_id,result=result,recorded_win_team_id=row.win_team_id,
                     explicit_dls=explicit_dls,target_adjusted=bool(adjusted_target),is_super_over=superover,
                     first_runs=None if a is None else int(a.total),second_runs=None if z is None else int(z.total),
                     second_wickets_lost=None if z is None else int(z.wickets),
                     implied_win_team_id=None,winner_match=None,margin_match=None,tie_score_match=None,reported_margin=None,implied_margin=None)
            if explicit_dls or adjusted_target:
                rec['assessment']='dls_or_adjusted_target'
            elif noresult:
                rec['assessment']='no_result_or_abandoned'
            elif a is None or z is None:
                rec['assessment']='missing_innings'
            elif superover:
                so1,so2=get(3),get(4)
                rec['regulation_tie']=bool(a.total==z.total)
                if so1 is None or so2 is None or so1.total==so2.total:
                    rec['assessment']='super_over_not_reconstructable'
                else:
                    implied=int(so2.team if so2.total>so1.total else so1.team)
                    rec.update(assessment='super_over_assessable',implied_win_team_id=implied,winner_match=bool(implied==row.win_team_id))
            elif re.search(r'tied|tie',result,re.I):
                equal=bool(a.total==z.total)
                rec.update(assessment='tie_assessable' if equal else 'tie_totals_inconsistent',tie_score_match=equal)
                if equal:
                    rec.update(winner_match=bool(pd.isna(row.win_team_id)),implied_win_team_id=0)
            else:
                implied=int(z.team if z.total>a.total else a.team if a.total>z.total else 0)
                rec['implied_win_team_id']=implied
                rec['winner_match']=bool(implied==row.win_team_id)
                margin=re.search(r'won\s+(?:by\s+)?(\d+)\s*(wickets?|wkts?|runs?)',result,re.I)
                if margin:
                    reported=int(margin[1])
                    calculated=DC['wickets_per_innings']-int(z.wickets) if margin[2].lower().startswith('w') else int(a.total-z.total)
                    rec.update(assessment='ordinary_assessable',reported_margin=reported,implied_margin=calculated,margin_match=bool(reported==calculated))
                else:
                    rec['assessment']='margin_unparsed'
            records.append(rec)
        df=pd.DataFrame(records)
        ordinary=df[df.assessment.eq('ordinary_assessable')]
        summaries.append(dict(formula=label,ordinary_assessable=len(ordinary),winner_matches=int(ordinary.winner_match.sum()),margin_matches=int(ordinary.margin_match.sum()),both_matches=int((ordinary.winner_match.eq(True)&ordinary.margin_match.eq(True)).sum())))
        validations[label]=df
    export(pd.DataFrame(summaries),'scoring_formula_comparison.csv')
    validation=validations['runs_plus_both_extras']
    export(validation,'match_reconciliation.csv')
    mismatch=validation[validation.winner_match.eq(False)|validation.margin_match.eq(False)|validation.tie_score_match.eq(False)]
    export(mismatch,'match_reconciliation_mismatches.csv')
    export(validation[~validation.assessment.isin(['ordinary_assessable','tie_assessable','super_over_assessable'])], 'match_reconciliation_not_assessable.csv')
    return validation,summaries

def main():
    tables=load()
    prof=profile(tables)
    b=tables['ball_by_ball'].copy()
    m=tables['matches'].copy()
    c=tables['competitions'].copy()
    mapping=tables['competition_team_player_mapping']
    teams=tables['teams']
    xi=tables['playing_eleven']
    checks={}
    def check(name,value):
        checks[name]=bool(value)
        if not value:
            raise AssertionError(name)
    for name,cols in [('matches',['match_id']),('competitions',['comp_id']),('teams',['comp_id','team_id']),('competition_team_player_mapping',['comp_id','team_id','player_id'])]:
        check(name+'_key_unique',not tables[name].duplicated(cols).any())
    xi_keys=['match_id','team_id','player_id']
    xi_repeated=xi[xi.duplicated(xi_keys,keep=False)]
    export(xi_repeated,'xi_repeated_keys.csv')
    check('xi_repeated_keys_other_flags_agree',not xi.groupby(xi_keys)[['is_played','is_captain','is_wk','is_impact','is_impact_off']].nunique(dropna=False).gt(1).any().any())
    roster=xi.drop(columns='batting_order').drop_duplicates(xi_keys)
    orders=xi.groupby(xi_keys).batting_order.agg(lambda s:';'.join(str(int(v)) for v in sorted(s.dropna().unique()))).rename('batting_order_values').reset_index()
    roster=roster.merge(orders,on=xi_keys,validate='one_to_one')
    roster['batting_order']=pd.to_numeric(roster.batting_order_values.where(~roster.batting_order_values.str.contains(';')),errors='coerce')
    check('delivery_key_unique',not b.duplicated(['match_id','innings','innings_ball_num']).any())
    check('no_exact_duplicate_deliveries',not b.duplicated().any())
    c['raw_match_format']=c.match_format
    c['competition_class']=np.where(c.comp_name.str.fullmatch(DC['ipl_name_pattern']), 'IPL',np.where(c.match_format.eq('T20I'),'T20I','OTHER_T20'))
    check('all_match_competitions_exist',m.comp_id.isin(c.comp_id).all())
    check('all_deliveries_have_matches',b.match_id.isin(m.match_id).all())
    canonical=mapping[['player_id','player_name']].drop_duplicates().rename(columns={'player_name':'display_name'}).sort_values('player_id').reset_index(drop=True)
    check('mapping_names_unique_per_player',not canonical.player_id.duplicated().any())
    check('canonical_display_names_non_null',canonical.display_name.notna().all())
    names=canonical.set_index('player_id').display_name
    export(canonical[canonical.display_name.duplicated(keep=False)],'canonical_name_collisions.csv')
    variants=[]
    for role in ['striker','non_striker','bowler']:
        check(role+'_canonical_id_coverage',b[role+'_id'].isin(names.index).all())
        wrong=b[b[role+'_name'].ne(b[role+'_id'].map(names))]
        for row in wrong[[role+'_id',role+'_name']].drop_duplicates().itertuples(index=False,name=None):
            variants.append({'player_id':row[0],'display_name':names.loc[row[0]],'source_role':role,'raw_source_name':row[1]})
        b[role+'_name']=b[role+'_id'].map(names)
    write_json(AUDIT/'raw_name_variants.json',variants)
    check('xi_canonical_id_coverage',xi.player_id.isin(names.index).all())
    dismissed=b.dismissed_player_id.dropna()
    check('dismissed_player_id_coverage',dismissed.isin(names.index).all())
    # Source-row IDs preserve delivery order; source indices count physical deliveries.
    b.insert(0,'delivery_id',np.arange(len(b),dtype=np.int64))
    b['total_runs']=b.runs+b.extras1_runs+b.extras_2_runs
    b['is_legal']=~b.extras_type.isin(DC['illegal_extras'])
    b['is_no_ball']=b.extras_type.isin(DC['no_ball_extras'])
    b['is_wide']=b.extras_type.eq('wide')
    b['batter_ball_faced']=~b.is_wide
    b['bowler_runs_conceded']=b.runs+np.where(b.extras_type.isin(DC['no_ball_extras']+['wide']),b.extras1_runs,0)
    b['bowler_wicket']=b.is_wicket & b.dismissal_type.isin(DC['bowler_wicket_types'])
    b['is_regular_innings']=b.innings.isin(DC['regular_innings'])
    # Unlabelled extras and inconsistent byes need provenance, not invented correction.
    b['ambiguous_extras']=(b.extras_type.isna()&(b.extras1_runs.ne(0)|b.extras_2_runs.ne(0))) | (b.extras_type.isin(DC['bye_extras'])&b.runs.ne(0))
    export(b[b.ambiguous_extras], 'ambiguous_extras_rows.csv')
    extras=b.groupby('extras_type',dropna=False).agg(deliveries=('runs','size'),batter_runs=('runs','sum'),extras1=('extras1_runs','sum'),extras2=('extras_2_runs','sum')).reset_index()
    export(extras,'extras_encoding.csv')
    over=b.groupby(['match_id','innings','overid']).agg(deliveries=('delivery_id','size'),legal_balls=('is_legal','sum'),first_over_ball=('over_ball_num','min'),last_over_ball=('over_ball_num','max')).reset_index()
    last=b.groupby(['match_id','innings']).overid.max().rename('last_over')
    over=over.merge(last,on=['match_id','innings'],validate='many_to_one')
    over['completed_before_final_over']=over.overid.lt(over.last_over)
    over['anomalous_completed_over']=over.completed_before_final_over & over.legal_balls.ne(DC['balls_per_over'])
    export(over,'over_legal_ball_audit.csv')
    export(over[over.anomalous_completed_over],'anomalous_completed_overs.csv')
    sequence=[]
    for keys,g in b.groupby(['match_id','innings'],sort=False):
        if not np.array_equal(g.innings_ball_num.to_numpy(),np.arange(1,len(g)+1)):
            sequence.append(dict(match_id=keys[0],innings=keys[1],kind='innings_ball_num_not_physical_sequence'))
        for overid,h in g.groupby('overid',sort=False):
            if not np.array_equal(h.over_ball_num.to_numpy(),np.arange(1,len(h)+1)):
                sequence.append(dict(match_id=keys[0],innings=keys[1],overid=overid,kind='over_ball_num_not_physical_sequence'))
    export(pd.DataFrame(sequence,columns=['match_id','innings','overid','kind']),'ball_number_sequence_issues.csv')
    validation,formula_summary=score_validation(b,m)
    m=m.merge(c,on='comp_id',validate='many_to_one')
    # Do not silently equate different IDs just because they share a display name.
    actors=pd.concat([b[['match_id','batting_team_id',role+'_id']].rename(columns={'batting_team_id':'team_id',role+'_id':'player_id'}) for role in ['striker','non_striker']] + [b[['match_id','bowling_team_id','bowler_id']].rename(columns={'bowling_team_id':'team_id','bowler_id':'player_id'})]).drop_duplicates()
    participation=actors.merge(roster,on=['match_id','team_id','player_id'],how='left',indicator=True,validate='one_to_one')
    participation['display_name']=participation.player_id.map(names)
    inconsistent=participation[participation['_merge'].ne('both')|~participation.is_played.eq(True)]
    export(inconsistent,'participation_inconsistencies.csv')
    v=validation.set_index('match_id')
    m['has_delivery_data']=m.match_id.isin(b.match_id)
    m['has_revised_fields']=m[['first_inn_revised_overs','second_inn_revised_overs','revised_target']].notna().any(axis=1)
    m['dls_or_adjusted_target']=m.match_id.map(v.explicit_dls|v.target_adjusted)
    m['super_over_match']=m.match_id.map(v.is_super_over)
    m['no_result_or_abandoned']=m.result.str.contains(r'no result|abandoned',case=False,na=False)
    m['reconciliation_mismatch']=m.match_id.map(v.winner_match.eq(False)|v.margin_match.eq(False)|v.tie_score_match.eq(False))
    m['legal_over_anomaly']=m.match_id.isin(over.loc[over.anomalous_completed_over,'match_id'])
    m['ambiguous_extras_match']=m.match_id.isin(b.loc[b.ambiguous_extras,'match_id'])
    m['participation_inconsistency']=m.match_id.isin(inconsistent.match_id)
    m['scope_primary']=m.competition_class.isin(DC['primary_competition_classes'])
    reason_cols=['has_revised_fields','dls_or_adjusted_target','super_over_match','no_result_or_abandoned','reconciliation_mismatch','legal_over_anomaly','ambiguous_extras_match','participation_inconsistency']
    policies={'has_revised_fields':'exclude_revised_matches','dls_or_adjusted_target':'exclude_revised_matches','super_over_match':'exclude_super_over_matches','no_result_or_abandoned':'exclude_unfinished_matches','reconciliation_mismatch':'quarantine_reconciliation_mismatches','legal_over_anomaly':'quarantine_legal_over_anomalies','ambiguous_extras_match':'quarantine_ambiguous_extras','participation_inconsistency':'quarantine_participation_inconsistencies'}
    active_reasons=[k for k in reason_cols if DC[policies[k]]]
    m['quality_reasons']=m.apply(lambda r:';'.join([k for k in active_reasons if r[k]]+([] if r.has_delivery_data else ['missing_deliveries'])),axis=1)
    m['analysis_candidate']=m.scope_primary & m.quality_reasons.eq('') & m.has_delivery_data
    # Derived limits are auditable only: conservative modelling excludes ALL revised matches.
    m['first_innings_limit_balls']=m.first_inn_revised_overs.fillna(DC['normal_innings_balls'])
    m['second_innings_limit_balls']=m.second_inn_revised_overs.fillna(DC['normal_innings_balls'])
    first_totals=b[b.innings.eq(1)].groupby('match_id').total_runs.sum()
    m['observed_first_innings_runs']=m.match_id.map(first_totals)
    m['derived_chase_target']=m.revised_target.fillna(m.observed_first_innings_runs+1)
    revised_evidence=[]
    for row in m[m.has_revised_fields].itertuples():
        for inn,field in [(1,'first_inn_revised_overs'),(2,'second_inn_revised_overs')]:
            g=b[b.match_id.eq(row.match_id)&b.innings.eq(inn)]
            revised_evidence.append(dict(match_id=row.match_id,innings=inn,source_field=field,source_value=getattr(row,field),observed_legal_balls=int(g.is_legal.sum()),observed_physical_deliveries=len(g),max_observed_over=None if g.empty else int(g.overid.max()),result=row.result))
    export(pd.DataFrame(revised_evidence),'revised_limits_evidence.csv')
    export(m,'match_quality.csv')
    # Evidence only: competition-team roster identity plus actual played appearances.
    team_classes=teams.merge(c[['comp_id','competition_class','comp_name','season']],on='comp_id',validate='many_to_one')
    national_teams=team_classes[team_classes.competition_class.eq('T20I')]
    mapping_national=mapping.merge(national_teams[['comp_id','team_id','team_name','season']],on=['comp_id','team_id'],how='inner',suffixes=('_mapping',''),validate='many_to_one')
    appearances=xi[xi.is_played.eq(True)].merge(m[['match_id','comp_id']],on='match_id',validate='many_to_one')
    appearances=appearances.merge(national_teams[['comp_id','team_id','team_name']],on=['comp_id','team_id'],how='inner',validate='many_to_one')
    appearance_counts=appearances.groupby(['comp_id','team_id','player_id']).match_id.nunique().rename('played_matches')
    national=mapping_national.merge(appearance_counts,on=['comp_id','team_id','player_id'],how='left',validate='one_to_one')
    national['played_matches']=national.played_matches.fillna(0).astype(int)
    national['display_name']=national.player_id.map(names)
    national=national[['player_id','display_name','comp_id','comp_name','season','team_id','team_name','played_matches']]
    export(national,'national_team_evidence.csv',AVAIL)
    # All XI national-team IDs must also have mapping evidence; otherwise stop before flags.
    national_keys=set(zip(national.comp_id,national.team_id,national.player_id))
    check('all_played_national_keys_have_mapping',all(key in national_keys for key in zip(appearances.comp_id,appearances.team_id,appearances.player_id)))
    by_player={pid:g for pid,g in national.groupby('player_id')}
    flags=[]
    borderline=[]
    for row in canonical.itertuples():
        evidence=by_player.get(row.player_id)
        observed=[] if evidence is None else sorted(evidence.team_name.unique())
        flagged=[country for team,country in DC['nationality_team_names'].items() if team in observed]
        flag=flagged[0] if len(flagged)==1 else 'unknown' if not observed or len(flagged)>1 else 'not_flagged'
        if evidence is None:
            detail='No T20I national-team evidence in supplied pack; not evidence of nationality.'
            confidence='unknown'
        else:
            detail=json.dumps(evidence[['comp_id','comp_name','team_id','team_name','played_matches']].to_dict('records'),ensure_ascii=False,separators=(',',':'))
            confidence='direct national-team roster evidence'
        flags.append(dict(player_id=row.player_id,display_name=row.display_name,flag=flag,evidence=detail,confidence=confidence))
        if not observed or len(observed)>1:
            teams_seen=sorted(mapping.loc[mapping.player_id.eq(row.player_id),'team_name'].unique())
            borderline.append(dict(player_id=row.player_id,display_name=row.display_name,reason='no_T20I_national_team_evidence' if not observed else 'multiple_national_teams',national_teams=';'.join(observed),mapped_teams=';'.join(teams_seen),decision='pending',source='competition_team_player_mapping.csv; competitions.csv; playing_eleven.csv'))
    flags=pd.DataFrame(flags)
    # User-reviewed nationality decisions are authoritative and survive rebuilds.
    if (AVAIL/'nationality_flags.csv').exists():
        existing=pd.read_csv(AVAIL/'nationality_flags.csv')
        check('user_nationality_input_ids_preserved',set(existing.player_id)==set(flags.player_id))
        flags=existing
    else:
        export(flags,'nationality_flags.csv',AVAIL)
    borderline=pd.DataFrame(borderline,columns=['player_id','display_name','reason','national_teams','mapped_teams','decision','source'])
    observed_ids=set(b.striker_id).union(b.non_striker_id,b.bowler_id)
    borderline['has_delivery_exposure']=borderline.player_id.isin(observed_ids)
    export(borderline,'nationality_borderline.csv',AVAIL)
    # Associate full evidence rows with each flagged person for explicit competition/team/match provenance.
    flagged_evidence=national[national.player_id.isin(flags.loc[flags.flag.isin(['Pakistan','Bangladesh']),'player_id'])]
    export(flagged_evidence,'nationality_flagged_evidence.csv',AVAIL)
    canonical=canonical.merge(flags[['player_id','flag']],on='player_id',validate='one_to_one').rename(columns={'flag':'nationality_flag'})
    b=b.merge(m[['match_id','comp_id','comp_name','season','raw_match_format','competition_class','match_date','venue_id','venue_country','analysis_candidate','quality_reasons','derived_chase_target','first_innings_limit_balls','second_innings_limit_balls']],on='match_id',validate='many_to_one',how='left').sort_values('delivery_id').reset_index(drop=True)
    check('joined_delivery_row_count_preserved',len(b)==len(tables['ball_by_ball']))
    check('joined_competition_season_non_null',b[['comp_id','competition_class','season']].notna().all().all())
    check('canonical_output_names',all(b[role+'_name'].eq(b[role+'_id'].map(names)).all() for role in ['striker','non_striker','bowler']))
    canonical.to_parquet(PROCESSED/'players.parquet',index=False)
    b.to_parquet(PROCESSED/'deliveries.parquet',index=False)
    m.to_parquet(PROCESSED/'matches.parquet',index=False)
    c.to_parquet(PROCESSED/'competitions.parquet',index=False)
    xi.to_parquet(PROCESSED/'playing_eleven.parquet',index=False)
    roster.to_parquet(PROCESSED/'participant_roster.parquet',index=False)
    teams.to_parquet(PROCESSED/'teams.parquet',index=False)
    export(canonical,'canonical_players.csv')
    # Preserve audit assertions without altering raw values or guessing corrections.
    standard=validation[validation.assessment.eq('ordinary_assessable')]
    summary=dict(rows={k:len(v) for k,v in tables.items()},canonical_players=len(canonical),
                 format_counts=c.raw_match_format.value_counts().to_dict(),competition_classes=c.groupby('competition_class').size().to_dict(),
                 match_classes=m.groupby('competition_class').size().to_dict(),first_match_date=m.match_date.min(),last_match_date=m.match_date.max(),
                 observed_delivery_matches=b.match_id.nunique(),missing_delivery_matches=int((~m.has_delivery_data).sum()),
                 ordinary_non_dls_matches=len(standard),winner_matches=int(standard.winner_match.sum()),margin_matches=int(standard.margin_match.sum()),
                 winner_match_rate=float(standard.winner_match.mean()),margin_match_rate=float(standard.margin_match.mean()),
                 reconciliation_assessments=validation.assessment.value_counts().to_dict(),reconciliation_mismatch_ids=validation.loc[validation.winner_match.eq(False)|validation.margin_match.eq(False)|validation.tie_score_match.eq(False),'match_id'].tolist(),
                 anomalous_completed_overs=int(over.anomalous_completed_over.sum()),completed_overs=int(over.completed_before_final_over.sum()),
                 ball_number_sequence_issues=len(sequence),name_variants=len(variants),nationality_flags=flags.flag.value_counts().to_dict(),
                 borderline_players=len(borderline),multiple_national_team_players=int(borderline.reason.eq('multiple_national_teams').sum()),
                 ambiguous_extras_rows=int(b.ambiguous_extras.sum()),participation_inconsistencies=len(inconsistent),xi_repeated_key_rows=len(xi_repeated),xi_repeated_key_matches=int(xi_repeated.match_id.nunique()),canonical_name_collision_rows=int(canonical.display_name.duplicated(keep=False).sum()),
                 borderline_with_delivery_exposure=int(borderline.has_delivery_exposure.sum()),borderline_roster_only=int((~borderline.has_delivery_exposure).sum()),bowl_speed_zero_rows=int(b.bowl_speed.eq(0).sum()),
                 super_over_deliveries=int((~b.is_regular_innings).sum()),revised_matches=int(m.has_revised_fields.sum()),
                 quality_reason_counts={k:int(m[k].sum()) for k in reason_cols},candidate_matches=int(m.analysis_candidate.sum()),
                 candidate_deliveries=int((b.analysis_candidate&b.is_regular_innings).sum()),formula_comparison=formula_summary)
    write_json(AUDIT/'phase1_summary.json',summary)
    versions={package:importlib.metadata.version(package) for package in ['pandas','numpy','pyarrow','pypdf']}
    write_json(AUDIT/'runtime_versions.json',dict(python=sys.version,packages=versions))
    write_json(AUDIT/'phase1_checks.json',checks)
    dictionary=['# Data dictionary and cleaning evidence','',
      'Generated by scripts/phase1.py from immutable supplied files. No records are repaired or deleted in the joined parquet; analysis_candidate is a conservative proposed modelling mask, not a player exclusion. All calculations in this phase include every supplied player. Rankings/model phases have not run.','',
      '## Verified scope and joins','',
      f"{len(b):,} deliveries; {len(m):,} matches; {len(c):,} competitions; {len(canonical):,} canonical players. Dates {m.match_date.min()} to {m.match_date.max()}.",
      'Unique keys: matches.match_id; competitions.comp_id; teams(comp_id,team_id); mapping(comp_id,team_id,player_id); derived participant_roster(match_id,team_id,player_id); deliveries(match_id,innings,innings_ball_num). Raw XI repeats keys in three super-over matches because batting orders vary without an innings column: preserve raw XI and derive participant roster after checking other flags agree. Store all order values, with ambiguous single orders missing. Canonical names come solely from mapping.player_name: one unique name per player ID. Different IDs can share a name (canonical_name_collisions.csv); never merge by name. Many-to-one joins preserve every delivery and attach season/raw format/class.',
      'Raw match_format is T20I/T20, NOT IPL/T20I. Derive IPL only from the five explicitly IPL-named competitions; retain two non-IPL T20 competitions as OTHER_T20. Team confirmed all three classes for the main model on 15 November 2026. Keep the emerging-team class separate from IPL for comparison/adjustment.', '',
      '## 1. Runs and extras','',
      'runs is batter-attributed runs, not team total. team total = runs + extras1_runs + extras_2_runs. Compare candidate formulas in outputs/audit/scoring_formula_comparison.csv. extras1 is wide/no-ball/byes/leg-byes/penalty amount depending on label; extras2 is additional byes/leg-byes on no-balls where labelled. Two extras-bearing rows lack a label and one legbyes-labelled row has a batter run; flag these rather than infer bowler attribution.',
      f"Ordinary non-DLS winner reconciliation: {int(standard.winner_match.sum())}/{len(standard)} ({standard.winner_match.mean():.4%}); margin reconciliation: {int(standard.margin_match.sum())}/{len(standard)} ({standard.margin_match.mean():.4%}). Full all-match classification and every mismatch/not-assessable case are exported. No score is assumed to be present in result text.",
      'Bowler debit = batter runs + wides/no-ball extras1; omit byes/legbyes/penalty and extras2. Ambiguous extras matches quarantined in proposed mask. Batter balls faced exclude wides but include no-balls (legal-ball pressure state uses the separate is_legal flag).', '',
      '## 2. Legal deliveries','',
      'wide, Overstep and other are illegal delivery encodings; byes/legbyes and otherwise labelled ordinary deliveries are legal. other acts like no-ball, supported by one extra penalty and completed-over accounting. Both over_ball_num and innings_ball_num count physical records, including illegal deliveries; neither is a legal-ball counter. Sequence audit is exported. Completed overs before the final observed over should contain six legal deliveries. Remaining anomalies are reported without repair.',
      f"Completed-over evidence: {int((over.completed_before_final_over & over.legal_balls.eq(DC['balls_per_over'])).sum())}/{int(over.completed_before_final_over.sum())} have six derived legal balls; {int(over.anomalous_completed_over.sum())} anomalies in outputs/audit/anomalous_completed_overs.csv.", '',
      '## 3. Targets, revisions and DLS','',
      'Ordinary chase target = observed first-innings team runs + 1; revised_target takes precedence in audit. Pre-delivery features are deferred to Phase 2. Despite their names, first_inn_revised_overs and second_inn_revised_overs hold delivery limits such as 114 and 48, consistent with 19 and 8 overs, not literal overs. Do not multiply them by six. All matches with any revised field are conservatively excluded from the proposed primary model. DLS text or adjusted targets are separately tagged for reconciliation; shortened non-DLS matches remain in the validation denominator.', '',
      '## 4. Venues','',
      'Only venue_id and venue_country are provided; no venue names are generated. Any venue/opposition adjustment must respect sample sizes in later phases.', '',
      '## 5. XI and Impact Player fields','',
      'XI includes unused squad entries (is_played=False), so do not count every row as a match appearance. is_impact and is_impact_off record substitutions, not retirement or nationality. Active participation must use is_played and actual delivery actors; batting_order can be missing or differ with substitutions and is not alone an eligibility rule. outputs/audit/participation_inconsistencies.csv reports conflicts. Pressure/baseline metrics will use actual observed exposure.', '',
      '## 6. Special cases, names and duplicates','',
      'innings 3/4 mark recorded super-over deliveries; results also identify super-over matches whose extra innings may be absent. Proposed modelling mask excludes entire super-over matches to avoid uncertain contexts. Abandoned/no-result matches are flagged, including those with no deliveries. Retire Out is recorded as a wicket; it is not retired hurt or career retirement. No retired-hurt label is present, so absence cannot prove no such interruption occurred. Dismissal identity and wicket credit are separate; run-outs, obstructing field and retired-out do not credit the bowler. Duplicate-key and exact-duplicate checks are in phase1_checks.json. Raw name variants, if any, remain internal evidence; output names are canonical.', '',
      '## 7. Competition formats','',
      'See outputs/audit/profiles.json and processed competitions.parquet. All 141 competitions are classified without assuming their names or formats. Empty future competition rosters remain identity evidence, not played match samples.', '',
      '## 8. Nationality evidence and open decisions','',
      'Only exact Pakistan and Bangladesh national-team entries in T20I competitions create permanent flags. No name-based inference and no automatic inference from Pakistan A/Bangladesh A is made. Mapping membership is squad evidence even when played_matches=0; actual match counts use is_played=True and distinct match_id. All played national-team keys are checked against mapping evidence.',
      'data/availability/national_team_evidence.csv provides competition/team/played counts. nationality_flags.csv has every canonical player. nationality_flagged_evidence.csv gives every flagged player provenance. nationality_borderline.csv lists EVERY player with no T20I national-team evidence or multiple national-team associations. Unknown is not cleared eligibility; user decisions are required before treating unknown candidates as available.', '',
      '## Modelling quarantine proposal','',
      f"{int(m.analysis_candidate.sum())} matches / {int((b.analysis_candidate&b.is_regular_innings).sum()):,} regular deliveries currently meet the conservative mask. This is a proposal for review, not a rating result.",
      'Reason columns and rows in match_quality.csv explain exclusions, including revisions/DLS, super overs, no results, scoring mismatches, malformed completed overs, ambiguous extras and unresolved actor/XI identities. User approved conservative quarantine; participation conflicts are included as an explicit identity-quality decision. Each quarantine policy has its own configuration switch. Format scope is separate from quality. No player/nationality filter is applied to modelling preparation.', '',
      '## Raw fields: observed dtype, nulls and sample values','']
    for name,entry in prof.items():
        dictionary += [f'### {name}.csv', '',f"Rows: {entry['rows']:,}; columns: {entry['columns']}; exact duplicate rows: {entry['exact_duplicate_rows']}.", '']
        for col,f in entry['fields'].items():
            dictionary.append(f"- `{col}`: {f['dtype']}; null {f['nulls']:,} ({f['null_rate']:.2%}); distinct {f['distinct_non_null']:,}; examples {json.dumps(f['samples'],ensure_ascii=False)}.")
        dictionary.append('')
    dictionary += ['## Derived fields','',
      '- delivery_id: stable zero-based original row ordinal, before any join/sort.',
      '- total_runs, is_legal, is_no_ball, is_wide, batter_ball_faced, bowler_runs_conceded, bowler_wicket: definitions above.',
      '- raw_match_format: unmodified format; competition_class: IPL/T20I/OTHER_T20; season: original supplied string (including cross-year seasons).',
      '- ambiguous_extras, quality_reasons, analysis_candidate: quality flags and proposed sample mask; no raw row deletion.',
      '- derived_chase_target and *_limit_balls: audit reconstruction; revised matches excluded pending treatment.',
      '- canonical_players: player_id/display_name/nationality_flag. National-team evidence is a rule flag, not a comprehensive verified citizenship field.',
      '', '## Reproduce', '', '`python run.py phase1` then `python run.py test` (Phase 1 checks only until subsequent phases are implemented). Read README for dependency installation.']
    (ROOT/'docs/data_dictionary.md').write_text('\n'.join(dictionary)+'\n',encoding='utf-8')
    print(json.dumps(summary,indent=2))

if __name__=='__main__':
    main()
