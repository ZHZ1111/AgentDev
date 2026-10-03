"""Offline audit fixtures for F3/F4; never reported as real model performance."""
import json

import pytest

from testgen_agent import experiment as e, models as m
from testgen_agent.config import AppConfig
from testgen_agent.llm_client import LLMError, LLMErrorCode
from test_generation import llm_result, single_function_generated


class SequenceClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.contexts = []

    def generate_tests(self, context):
        self.contexts.append(context)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return llm_result(response)


def mean_candidate(empty=False):
    first = single_function_generated('safe_mean', code='from subject import safe_mean\ndef test_behavior():\n    assert safe_mean([2, 4]) == 3.0\n')
    if not empty:
        return first
    scenario = first.plan.scenarios[0].updated(scenario_id='empty', category='boundary',
                                              expected_behavior='empty returns 0.0')
    return first.updated(plan=first.plan.updated(scenarios=(*first.plan.scenarios, scenario)),
        mappings=(*first.mappings, m.TestCaseMapping(test_function='test_empty', scenario_ids=('empty',))),
        code=first.code+'\ndef test_empty():\n    assert safe_mean([]) == 0.0\n')


@pytest.fixture(scope='module')
def paired(tmp_path_factory):
    client = SequenceClient([mean_candidate(), mean_candidate(True)])
    config = AppConfig(model='offline-synthetic-model', api_key='offline-fixture')
    root = e.run_experiment(tmp_path_factory.mktemp('experiment'), config=config, client=client,
                            provenance='offline_fixture', case_ids=['mean'])
    return root, client


def test_shared_seed_and_real_feedback_evidence(paired):
    root, client = paired
    report = e.rebuild(root)
    assert len(client.contexts) == 2
    assert report['fairness_all_shared_first_candidates_identical']
    assert report['physical_cost']['http_attempts'] == 2
    assert report['physical_cost']['actual_network_http_attempts'] == 0
    assert report['aggregate']['baseline']['credited_http_attempts'] == 1
    assert report['aggregate']['feedback']['credited_http_attempts'] == 2
    b, f = [report['cases'][0]['modes'][mode] for mode in e.MODES]
    assert b['all_passed'] and f['all_passed']
    assert b['branch_percent'] == 50 and f['branch_percent'] == 100
    assert b['status'] == 'partial' and f['status'] == 'completed'
    assert f['candidate_rounds'] == f['selected_round'] == 2
    assert report['aggregate_by_split']['holdout']['baseline']['tasks'] == 0
    # Evaluator annotations, private oracles and mutant descriptions are never prompts.
    assert all('mean_empty_division' not in c.user_prompt for c in client.contexts)


def test_known_source_runtime_bug_counts_only_with_passing_reference(paired):
    root, _ = paired
    report = e.rebuild(root)
    variants = report['cases'][0]['variants']
    assert variants['baseline'][0]['status'] == 'not_detected'
    assert variants['feedback'][0]['status'] == 'detected'
    failure = variants['feedback'][0]['attributed_failures'][0]
    assert failure['exception_type'] == 'ZeroDivisionError'
    assert failure['affected_function'] == 'safe_mean'
    assert variants['feedback'][0]['unchanged_tests']


def test_offline_rebuild_ignores_prior_summary_and_external_dataset(paired, monkeypatch):
    root, client = paired
    expected = e.rebuild(root)
    (root/'summary.json').write_text('{}', encoding='utf-8')
    monkeypatch.setattr(e, 'BenchmarkDataset', lambda *args: pytest.fail('dataset read during rebuild'))
    assert e.rebuild(root) == expected
    assert len(client.contexts) == 2
    assert (root/'cases.csv').read_text(encoding='utf-8-sig').startswith('case_id,split,mode')


def test_altered_mutant_tests_fail_counterfactual_gate(paired):
    root, _ = paired
    path = root/'cases/mean/variants/feedback/mean_empty_division/rounds/01/test_subject.py'
    original = path.read_bytes()
    try:
        path.write_bytes(original+b'\n# altered\n')
        outcome = e.rebuild(root)['cases'][0]['variants']['feedback'][0]
        assert outcome['status'] == 'not_evaluable'
        assert not outcome['unchanged_tests']
    finally:
        path.write_bytes(original)
        e.rebuild(root)


def test_import_environment_failure_is_not_a_detection(paired):
    root, _ = paired
    path = root/'cases/mean/variants/feedback/mean_empty_division/execution.json'
    original = path.read_bytes()
    value = json.loads(original)
    value['failures'][0]['exception_type'] = 'ImportError'
    try:
        e.write_json(path, value)
        report = e.rebuild(root)
        outcome = report['cases'][0]['variants']['feedback'][0]
        assert outcome['status'] == 'not_evaluable'
        assert report['aggregate']['feedback']['evaluable_variants'] == 0
        assert report['aggregate']['feedback']['detection_rate'] is None
    finally:
        path.write_bytes(original)
        e.rebuild(root)


def test_export_and_cost_evidence_must_agree(paired):
    root, _ = paired
    path = root/'cases/mean/baseline/cost.json'
    original = path.read_bytes()
    value = json.loads(original)
    value['additional_calls'] = [{'attempts': 1, 'usage': None}]
    try:
        e.write_json(path, value)
        with pytest.raises(ValueError, match='evidence disagree'):
            e.rebuild(root)
    finally:
        path.write_bytes(original)
        e.rebuild(root)


def test_unmapped_failure_cannot_be_attributed(paired):
    root, _ = paired
    path = root/'cases/mean/variants/feedback/mean_empty_division/execution.json'
    original = path.read_bytes()
    value = json.loads(original)
    value['failures'][0]['nodeid'] = 'test_subject.py::test_unknown'
    try:
        e.write_json(path, value)
        outcome = e.rebuild(root)['cases'][0]['variants']['feedback'][0]
        assert outcome['status'] == 'unattributed_failure'
        assert not outcome['attributed_failures']
    finally:
        path.write_bytes(original)
        e.rebuild(root)


def test_unavailable_coverage_and_branch_na_keep_denominators(paired):
    root, _ = paired
    case = e.rebuild(root)['cases'][0]
    unavailable = json.loads(json.dumps(case))
    for mode in e.MODES:
        unavailable['modes'][mode].update(coverage_status='unavailable', line_percent=None, branch_percent=None)
    no_branch = json.loads(json.dumps(case))
    for mode in e.MODES:
        no_branch['modes'][mode].update(branch_not_applicable=True, branch_percent=None)
    report = e.aggregate([case, unavailable, no_branch])['baseline']
    assert report['tasks'] == 3 and report['all_passed_tasks'] == 3
    assert report['line_percent_available_tasks'] == 2
    assert report['branch_percent_available_tasks'] == 1
    assert report['coverage_unavailable_tasks'] == report['branch_not_applicable_tasks'] == 1
    assert report['mean_branch_percent'] == 50


def test_archive_rebuilds_without_original_paths_and_excludes_databases(paired, tmp_path):
    root, _ = paired
    destination = tmp_path/'saved'
    index = e.archive(root, destination)
    assert index['file_count'] > 40
    assert not any('.coverage' in path or '__pycache__' in path for path in index['files'])
    assert e.rebuild(destination) == e.rebuild(root)
    for path, value in index['files'].items():
        assert e.digest((destination/path).read_bytes()) == value['sha256']
    with pytest.raises(ValueError, match='already exists'):
        e.archive(root, destination)
    with pytest.raises(ValueError, match='outside'):
        e.archive(root, root/'nested')


def test_first_response_error_is_replayed_without_second_provider_call():
    class Context:
        def canonical_json(self):
            return '{}'
    error = LLMError(LLMErrorCode.TIMEOUT, 'safe timeout', attempts=2, retryable=True)
    client = SequenceClient([])
    for _ in e.MODES:
        wrapper = e.SharedSeedClient(client, error, Context())
        with pytest.raises(LLMError) as caught:
            wrapper.generate_tests(Context())
        assert caught.value is error
    assert client.contexts == []


def test_first_context_difference_is_rejected():
    class Context:
        def __init__(self, value):
            self.value = value
        def canonical_json(self):
            return self.value
    client = SequenceClient([])
    wrapper = e.SharedSeedClient(client, llm_result(mean_candidate()), Context('first'))
    with pytest.raises(ValueError, match='initial prompt differs'):
        wrapper.generate_tests(Context('changed'))
    assert client.contexts == []


@pytest.mark.parametrize('values,expected', [([], None), ([None], None),
    ([{'prompt_tokens': 2, 'completion_tokens': 3, 'total_tokens': 5}]*2,
     {'prompt_tokens': 4, 'completion_tokens': 6, 'total_tokens': 10}),
    ([{'prompt_tokens': None, 'completion_tokens': 3, 'total_tokens': None}],
     {'prompt_tokens': None, 'completion_tokens': 3, 'total_tokens': None})])
def test_missing_usage_is_not_fabricated(values, expected):
    assert e.usage_sum(values) == expected
