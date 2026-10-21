from types import SimpleNamespace
import pytest
from unknownid.eval import baselines


@pytest.mark.parametrize('support30,support40,selected',[(0.9,0.2,30),(0.2,0.9,40),(0.8,0.8,30)])
def test_oracle_independent_branches(monkeypatch,support30,support40,selected):
    initial = {'truth':0.5,'other':0.5}
    created = []
    class State:
        def __init__(self,*args,**kwargs):
            self.weights = dict(initial)
            self.actions = []
            self.evidence = {}
            self.snapshots = [dict(initial)]
            created.append(self)
        def measure(self,energy):
            assert not self.actions
            assert self.weights == initial
            support = {30:support30,40:support40}[energy]
            self.weights = {'truth':support,'other':1-support}
            self.actions.append(energy)
            self.snapshots.append(self.weights)
        def stage(self,k):
            return SimpleNamespace(order=lambda: sorted(self.weights,key=self.weights.get,reverse=True))
    monkeypatch.setattr(baselines,'PolicyState',State)
    state = SimpleNamespace(case=None,references=None,evaluator=None,error_model=None,tempering=0.85)
    baselines.OracleBestAction('truth').run(state,budget=1)
    assert len(created) == 2
    assert state.actions == [selected]
    assert len(state.snapshots) == 2


def test_oracle_budget_zero(monkeypatch):
    monkeypatch.setattr(baselines,'PolicyState',lambda *a,**k: pytest.fail('no optional measurement allowed'))
    state = SimpleNamespace(actions=[])
    baselines.OracleBestAction('truth').run(state,budget=0)
    assert state.actions == []
