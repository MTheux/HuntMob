import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from huntmob import deep_dast


class DeepDastTests(unittest.TestCase):
    def test_dynamic_gate_rejects_failed_or_zero_coverage_reports(self):
        lab = {'id': 'lab', 'package_id': 'com.lab.app', 'apk_sha256': 'a' * 64}
        report = {'lab_id': 'lab', 'package_id': 'com.lab.app', 'apk_sha256': 'a' * 64,
                  'job_id': 'dyn_one', 'source_sha256': 'b' * 64, 'session_state': 'failed',
                  'summary': {'observed_monitors': 1, 'network_requests': 0}}
        self.assertFalse(deep_dast._dynamic_evidence_ready(report, lab)[0])
        report['session_state'] = 'stopped'; report['summary']['observed_monitors'] = 0
        self.assertFalse(deep_dast._dynamic_evidence_ready(report, lab)[0])

    def test_dynamic_gate_rejects_unattributed_network_and_screenshot_only_coverage(self):
        lab = {'id': 'lab', 'package_id': 'com.lab.app', 'apk_sha256': 'a' * 64}
        report = {'lab_id': 'lab', 'package_id': 'com.lab.app', 'apk_sha256': 'a' * 64,
                  'job_id': 'dyn_one', 'source_sha256': 'b' * 64, 'session_state': 'stopped',
                  'summary': {'observed_monitors': 0, 'network_requests': 1, 'screenshots': 1}}
        self.assertFalse(deep_dast._dynamic_evidence_ready(report, lab)[0])
        report['summary']['observed_monitors'] = 1
        self.assertTrue(deep_dast._dynamic_evidence_ready(report, lab)[0])

    def test_ai_schema_closes_enum_and_extra_property_bypasses(self):
        correlation = deep_dast.AI_SCHEMA['properties']['correlations']['items']
        self.assertFalse(correlation['additionalProperties'])
        self.assertNotIn('no_evidence', correlation['properties']['status']['enum'])
        self.assertNotIn('low', correlation['properties']['confidence']['enum'])

    def test_run_requests_strict_schema_and_completes_with_known_evidence(self):
        lab = {'id': 'lab', 'engagement': 'authorized', 'package_id': 'com.lab.app', 'apk_sha256': 'a' * 64}
        dast = {'source_sha256': 'b' * 64}
        evidence = {'evidence_id': 'ev_known', 'normalized_result': {}}
        context = {'lab': lab, 'dast': dast, 'rea_jobs': [{'evidence': evidence}],
                   'gates': [{'passed': True}]}
        report = {'summary': 'Correlação limitada.', 'correlations': [], 'hypotheses': [],
                  'unknowns': ['Cobertura limitada.'], 'next_tests': ['Ampliar cobertura autorizada.']}
        response = {'model': 'hermes3:8b', 'done': True, 'message': {'content': json.dumps(report)}}
        job = {'job_id': 'deep_one'}
        with tempfile.TemporaryDirectory() as directory, \
                patch('huntmob.deep_dast.root', return_value=Path(directory)), \
                patch('huntmob.deep_dast.reverse_engines._ollama', return_value=response) as ollama:
            deep_dast._run(job, context)
        self.assertEqual(job['state'], 'complete')
        payload = ollama.call_args.args[1]
        self.assertEqual(payload['format'], deep_dast.AI_SCHEMA)
        user_prompt = json.loads(payload['messages'][1]['content'])
        self.assertEqual(user_prompt['allowed_evidence_ids'], ['DAST:' + 'b' * 64, 'ev_known'])

    def test_ai_correlations_require_known_evidence_ids(self):
        report = {
            'summary': 'Correlação limitada às evidências fornecidas.',
            'correlations': [{'title': 'Transporte observado', 'status': 'candidate',
                              'confidence': 'likely', 'evidence_ids': ['DAST:a'],
                              'analysis': 'O fluxo dinâmico e a leitura estática precisam de validação humana.'}],
            'hypotheses': [], 'unknowns': ['Impacto no backend não avaliado.'],
            'next_tests': ['Reproduzir no ambiente autorizado com controle negativo.'],
        }
        self.assertEqual(deep_dast._validate_ai(report, {'DAST:a'})['correlations'][0]['status'], 'candidate')
        report['correlations'][0]['evidence_ids'] = ['invented']
        with self.assertRaises(ValueError):
            deep_dast._validate_ai(report, {'DAST:a'})

    def test_jev_done_requires_every_observed_transition_and_digest(self):
        phases = [{'id': 'scope', 'state': 'complete', 'observable': 'scope bound', 'evidence_sha256': 'a' * 64},
                  {'id': 'rea', 'state': 'failed', 'observable': 'REA complete', 'evidence_sha256': ''}]
        result = deep_dast._jev_contract([{'passed': True}], phases)
        self.assertFalse(result['done_allowed'])
        self.assertFalse(result['executor_invoked'])

    def test_start_fails_closed_when_any_gate_is_missing(self):
        context = {'ready': False, 'lab': {'id': 'huntmob_lab_' + 'a' * 32},
                   'gates': [{'id': 'rea-evidence', 'passed': False, 'detail': 'missing'}]}
        with patch('huntmob.deep_dast.prerequisites', return_value=context):
            result = deep_dast.start()
        self.assertFalse(result['ok'])
        self.assertEqual(result['state'], 'blocked')

    def test_completed_jev_contract_is_explicit_about_canvas_limit(self):
        phases = [{'id': 'scope', 'state': 'complete', 'observable': 'scope bound', 'evidence_sha256': 'a' * 64}]
        result = deep_dast._jev_contract([{'passed': True}], phases)
        self.assertTrue(result['done_allowed'])
        self.assertIn('canvas', result['compatibility'])
