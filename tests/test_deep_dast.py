import unittest
from unittest.mock import patch

from huntmob import deep_dast


class DeepDastTests(unittest.TestCase):
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
