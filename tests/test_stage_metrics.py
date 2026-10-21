from unknownid.eval.baselines import Snapshot
from unknownid.eval.evaluate import _case_metrics, summarize_policy
from unknownid.core.models import Evidence


def test_selective_metrics_use_each_stage():
    evidence = {'A': Evidence(candidate_id='A', similarity_by_energy={20:0.9}, matched_peaks_by_energy={20:4}, log_score=1,weight=1)}
    snapshots = [Snapshot(0,{'A':0.5,'B':0.5},evidence,[],1),
                 Snapshot(1,{'A':0.95,'B':0.05},evidence,[30],0.1),
                 Snapshot(2,{'A':0.1,'B':0.9},evidence,[30,40],0.2)]
    class State:
        def stage(self,k): return snapshots[k]
    metrics = _case_metrics(State(),'A',budget=2,confidence=dict(min_support=.72,min_margin=.22,min_similarity=.3,min_matched=2))
    assert metrics['coverage_0'] == 0
    assert metrics['coverage_1'] == metrics['accepted_correct_1'] == 1
    assert metrics['top1_2'] == 0
    assert metrics['scans_0'] == 0
    assert metrics['total_acquisitions_1'] == 2
    metrics.update(runtime_s=0)
    summary = summarize_policy({'a':metrics},['a'],seed=1)
    assert summary['coverage_1'] == 1
    assert summary['risk_0'] is None
    assert summary['risk_1'] == 0
