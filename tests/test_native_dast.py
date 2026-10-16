import json
import unittest
from huntmob.native_dast import analyze, render_html


def source(events=None, network=None):
    return {'receipt':{'id':'dyn_'+'a'*32,'lab_id':'huntmob_lab_'+'b'*32,'package_id':'com.lab.app','apk_sha256':'f'*64,'scripts':['crypto-observe','tls-observe'],'state':'stopped'},'events':events or [],'network':network or [],'screenshots':[]}


class NativeDastTests(unittest.TestCase):
    def test_http_password_fields_create_evidence_linked_candidate(self):
        flow={'id':'real-flow','scheme':'http','path':'/login','method':'POST','host':'10.0.2.2','port':8888,'request':{'body':'username=%5BREDACTED%5D&password=%5BREDACTED%5D'}}
        report=analyze(source(network=[flow]))
        self.assertEqual(report['candidates'][0]['rule_id'],'http-credential-fields')
        self.assertEqual(report['candidates'][0]['evidence'][0]['id'],'real-flow')
        self.assertEqual(report['candidates'][0]['finding_status'],'candidate_review_required')

    def test_https_does_not_create_cleartext_candidate(self):
        flow={'id':'tls','scheme':'https','request':{'body':'password=%5BREDACTED%5D'}}
        self.assertEqual(analyze(source(network=[flow]))['candidates'],[])

    def test_ready_tls_hook_is_not_a_successful_tls_security_test(self):
        report=analyze(source(events=[{'script':'tls-observe','kind':'hook_ready','class_name':'SSLContext'}]))
        tls=next(x for x in report['coverage'] if x['id']=='tls-observe')
        self.assertEqual(tls['state'],'ready_not_exercised')
        self.assertEqual(report['candidates'],[])

    def test_missing_hook_does_not_become_missing_security_control(self):
        report=analyze(source(events=[{'script':'tls-observe','kind':'hook_unavailable'}]))
        self.assertEqual(report['candidates'],[])
        self.assertEqual(next(x for x in report['coverage'] if x['id']=='tls-observe')['state'],'unavailable')

    def test_ecb_candidate_contains_exact_event_reference(self):
        event={'script':'crypto-observe','kind':'call','class_name':'javax.crypto.Cipher','method':'getInstance','algorithm':'AES/ECB/PKCS5Padding'}
        report=analyze(source(events=[event]))
        self.assertEqual(report['candidates'][0]['evidence'][0]['event_index'],0)
        self.assertIn('ECB',report['candidates'][0]['title'])

    def test_modern_crypto_and_webview_bridge_are_observations_only(self):
        events=[{'script':'crypto-observe','kind':'call','algorithm':'AES/GCM/NoPadding'},{'script':'webview-observe','kind':'call','method':'addJavascriptInterface'}]
        report=analyze(source(events=events))
        self.assertEqual(report['candidates'],[])
        self.assertEqual(len(report['observations']),2)

    def test_report_html_escapes_app_and_evidence_values(self):
        data=source(network=[{'scheme':'http','id':'<script>danger</script>','path':'/'}]);data['receipt']['package_id']='<script>danger</script>'
        text=render_html(analyze(data)).decode()
        self.assertNotIn('<script>danger</script>',text)
        self.assertIn('&lt;script&gt;danger&lt;/script&gt;',text)

    def test_source_digest_changes_when_evidence_changes(self):
        first=analyze(source());second=analyze(source(events=[{'kind':'agent_ready'}]))
        self.assertNotEqual(first['source_sha256'],second['source_sha256'])

    def test_report_describes_every_monitor_and_network_totals(self):
        report=analyze(source(network=[{'id':'a','scheme':'https','host':'lab.local','status':500},{'id':'b','scheme':'http','host':'lab.local','state':'error'}]))
        self.assertEqual(len(report['checks']),6)
        self.assertTrue(all(item['evaluated'] and item['next_step'] for item in report['checks']))
        self.assertEqual(report['network_summary']['hosts'],['lab.local'])
        self.assertEqual(report['network_summary']['http_errors'],1)
        self.assertEqual(report['network_summary']['connection_failures'],1)

    def test_html_includes_observations_without_promoting_them_to_findings(self):
        report=analyze(source(events=[{'script':'webview-observe','kind':'call','method':'addJavascriptInterface'}]))
        text=render_html(report).decode()
        self.assertIn('Bridge JavaScript registrada',text)
        self.assertIn('O que foi avaliado',text)
        self.assertEqual(report['candidates'],[])

    def test_manual_security_checks_are_explicitly_not_assessed(self):
        report=analyze(source())
        self.assertEqual(len(report['manual_checks']),6)
        self.assertTrue(all(item['state']=='not_assessed' for item in report['manual_checks']))
