#!/usr/bin/env python3
"""Validate recovered public text features and expose arithmetic/duplicate diagnostics."""
from __future__ import annotations
import argparse
import collections
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics


def load(path):
    with path.open(encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def write(path, rows):
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)


def analyze(root: Path) -> dict:
    hashes = json.loads((root/'output_hashes.json').read_text())
    for name, expected in hashes.items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest() != expected:
            raise ValueError(f'Upstream output hash mismatch: {name}')
    sample = load(root/'sample_text_features.csv')
    docs = load(root/'archive_document_manifest.csv')
    coef = load(root/'word_coefficients.csv')
    controls = load(root/'same_day_control_candidates.csv')
    events = load(root/'event_174_text_features.csv')
    if len(sample)!=43687 or len(docs)!=36750 or len(events)!=174:
        raise ValueError('Unexpected pinned-corpus size')
    keyed = {(r['PERMNO'],r['date']):r for r in sample}
    if len(keyed)!=len(sample):
        raise ValueError('Sample key duplication')
    scored=sorted((r for r in sample if r['Soft']),key=lambda r:(r['date'],int(r['PERMNO'])))
    calibration=scored[0]
    intercept=float(calibration['Soft'])-float(calibration['selected_fitted_word_contribution_no_intercept'])
    errors=[abs(float(r['Soft'])-(intercept+float(r['selected_fitted_word_contribution_no_intercept']))) for r in scored]
    tolerance=1e-12
    if len(scored)!=36750 or max(errors)>tolerance:
        raise ValueError('Source-model arithmetic reconstruction failed')
    missing_disagreements=sum(bool(r['Soft']) != (int(r['text_document_count'])>0) for r in sample)
    if missing_disagreements:
        raise ValueError('Soft/text missingness unexpectedly differs')
    groups=collections.defaultdict(list)
    for doc in docs:
        if (doc['PERMNO'],doc['date']) not in keyed:
            raise ValueError('Unmatched text document')
        groups[doc['sha256']].append(doc)
    duplicate_groups={h:rows for h,rows in groups.items() if len(rows)>1}
    duplicate_rows=[]; cross_issuer_rows=[]
    for digest, group in sorted(duplicate_groups.items()):
        issuers={keyed[(d['PERMNO'],d['date'])]['GVKEY'] for d in group}
        for d in group:
            s=keyed[(d['PERMNO'],d['date'])]
            row={k:s[k] for k in ('PERMNO','GVKEY','SYMBOL','date','Hacked','Actual')}
            row.update({'content_sha256':digest,'group_rows':len(group),'group_issuer_count':len(issuers),
                        'member':d['member'],'split_policy':'KEEP_IDENTICAL_TEXT_TOGETHER',
                        'review_status':'CROSS_ISSUER_REVIEW' if len(issuers)>1 else 'SHARED_ISSUER_TEXT'})
            duplicate_rows.append(row)
            if len(issuers)>1: cross_issuer_rows.append(row)
    pool_counts=collections.Counter(r['source_trade_row'] for r in controls)
    if set(pool_counts)!={r['source_trade_row'] for r in events}:
        raise ValueError('Events missing from candidate pool')
    event_by_id={r['source_trade_row']:r for r in events}
    if len({(r['source_trade_row'],r['candidate_PERMNO'],r['date']) for r in controls})!=len(controls):
        raise ValueError('Duplicate candidate pair')
    for r in controls:
        target=event_by_id[r['source_trade_row']]
        if r['date']!=target['date'] or r['treated_PERMNO']!=target['PERMNO']:
            raise ValueError('Control target/date mismatch')
        c=keyed[(r['candidate_PERMNO'],r['date'])]
        if c['Hacked']!='0' or c['Actual']!='0' or r['treated_PERMNO']==r['candidate_PERMNO']:
            raise ValueError('Invalid unexposed control candidate')
    active={r['word']:float(r['coef']) for r in coef if float(r['coef'])!=0}
    cohort_stats=[]
    for h,a in [('0','0'),('1','0'),('1','1')]:
        rows=[r for r in sample if (r['Hacked'],r['Actual'])==(h,a)]
        values=[float(r['Soft']) for r in rows if r['Soft']]
        novelty=[float(r['prior_text_jaccard_distance']) for r in rows if r.get('prior_text_jaccard_distance')]
        cohort_stats.append({'Hacked':int(h),'Actual':int(a),'rows':len(rows),'scored_rows':len(values),
                             'mean_published_soft':statistics.mean(values),'median_published_soft':statistics.median(values),
                             'mean_absolute_soft':statistics.mean(map(abs,values)),
                             'prior_text_comparisons':len(novelty),'mean_text_jaccard_distance':statistics.mean(novelty)})
    model={'status':'RETROSPECTIVE_SOURCE_MODEL_ARITHMETIC_RECONSTRUCTION_ONLY',
           'source_commit':'c23c7d79d067a79d70cf20e31b072d3703497eae',
           'intercept':intercept,'intercept_derivation':'One earliest scored source row; every remaining source score checked separately.',
           'calibration_reference':{k:calibration[k] for k in ('PERMNO','SYMBOL','date','Soft')},
           'active_coefficients':active,'zero_coefficients_omitted':len(coef)-len(active),
           'preprocessing':{'tokenizer':'[a-z]+ after lowercasing','stopword_count':198,
                            'stopwords_sha256':'47608d511aa4fec95139d41e487109ab4a260313745d397210dbf966b1d3c225',
                            'stemmer':'NLTK 3.9.1 PorterStemmer default','word_limit':400,
                            'limit_applied':'After stopword removal; before CountVectorizer length filtering',
                            'vectorizer':'Term counts; only tokens of at least 2 characters'},
           'maximum_absolute_reconstruction_error':max(errors),'reconstruction_tolerance':tolerance,
           'not_out_of_sample_return_validation':True,'live_trading_eligible':False,'preannouncement_eligible':False}
    findings={'status':'VALIDATED_RETROSPECTIVE_RESEARCH', 'upstream_files_hash_verified':len(hashes),
              'model_reconstruction':{'scored_rows':len(scored),'intercept_calibration_rows':1,
                                      'additional_arithmetic_checks':len(scored)-1,'intercept':intercept,
                                      'maximum_absolute_error':max(errors),'tolerance':tolerance,
                                      'active_coefficients':len(active),'zero_coefficients':len(coef)-len(active),
                                      'interpretation':'Reconstructs a published fitted score; does not validate returns or tradability.'},
              'text_identity':{'text_rows':len(docs),'unique_content_hashes':len(groups),
                               'duplicate_groups':len(duplicate_groups),'rows_in_duplicate_groups':len(duplicate_rows),
                               'cross_issuer_groups':len({r['content_sha256'] for r in cross_issuer_rows}),
                               'cross_issuer_rows':cross_issuer_rows,'empty_documents':sum(int(d['text_characters'])==0 for d in docs),
                               'replacement_characters':sum(int(d['replacement_characters']) for d in docs)},
              'missingness':{'soft_text_availability_disagreements':missing_disagreements,
                             'missing_soft_rows_still_missing':sum(not r['Soft'] for r in sample),
                             'missing_soft_events_still_missing':sum(not r['Soft'] for r in events)},
              'control_candidates':{'pairs':len(controls),'covered_events':len(pool_counts),
                                    'unique_security_date_candidates':len({(r['candidate_PERMNO'],r['date']) for r in controls}),
                                    'unique_candidate_securities':len({r['candidate_PERMNO'] for r in controls}),
                                    'minimum_per_event':min(pool_counts.values()),'median_per_event':statistics.median(pool_counts.values()),
                                    'maximum_per_event':max(pool_counts.values()),
                                    'events_with_fewer_than_three_candidates':sum(n<3 for n in pool_counts.values()),
                                    'accepted_G5_matches':0},
              'retrospective_cohorts':cohort_stats,
              'not_estimated':['causal_effect','excess_return','out_of_sample_model_accuracy','trading_profitability'],
              'canonical_G1_G2_G3_G4_G5_modified':False,
              'validation_checks':['Upstream artifact SHA-256 verification','Pinned source expected row counts',
                                   'Unique source security/date keys','Complete exact-key text linkage',
                                   '36749 additional arithmetic checks after one-row intercept calibration',
                                   'Exact text/Soft missingness equivalence','All 174 control pools independently rechecked',
                                   'Unexposed/same-date/different-security control eligibility checked']}
    (root/'recovered_soft_model.json').write_text(json.dumps(model,indent=2)+'\n')
    (root/'deep_analysis_findings.json').write_text(json.dumps(findings,indent=2)+'\n')
    write(root/'duplicate_text_review.csv',duplicate_rows)
    write(root/'cross_issuer_text_review.csv',cross_issuer_rows)
    return findings


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,default=Path('data/processed/hacked_earnings_deep'))
    args=p.parse_args()
    print(json.dumps(analyze(args.input),indent=2))
