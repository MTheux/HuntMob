import json
import os
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from huntmob.device_mcp import WorkerClient, Server, NoRedirect, TOOLS

LAB = 'huntmob_lab_' + 'a' * 32
DEVICE = 'huntmob_lab_' + 'b' * 32


class DeviceMcpTests(unittest.TestCase):
    def test_transport_initialization_and_bounded_tools(self):
        server = Server(Mock())
        self.assertIn('error', server.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}))
        initialized = server.handle({'jsonrpc': '2.0', 'id': 2, 'method': 'initialize', 'params': {'protocolVersion': '2025-03-26'}})
        self.assertEqual(initialized['result']['protocolVersion'], '2025-03-26')
        result = server.handle({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/list'})
        self.assertEqual({t['name'] for t in result['result']['tools']}, {'devices_list', 'device_screenshot', 'android_create', 'android_power','ios_catalog','ios_create','device_power','reverse_target','reverse_context','reverse_jobs','reverse_inspect','reverse_record_review'})
        self.assertIsNone(server.handle({'jsonrpc': '2.0', 'method': 'notifications/initialized'}))

    def test_stdio_subprocess_emits_only_jsonrpc_and_no_startup_logs(self):
        messages = [{'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-03-26'}}, {'jsonrpc': '2.0', 'method': 'notifications/initialized'}, {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}]
        process = subprocess.run([sys.executable, '-m', 'huntmob.device_mcp', '--workspace', LAB], input='\n'.join(json.dumps(m) for m in messages)+'\n', capture_output=True, text=True, timeout=10, env={**os.environ, 'PYTHONPATH': 'src'})
        self.assertEqual(process.returncode, 0, process.stderr)
        responses = [json.loads(line) for line in process.stdout.splitlines()]
        self.assertEqual([r['id'] for r in responses], [1, 2])
        self.assertEqual(len(responses[1]['result']['tools']), 12)

    def test_arbitrary_target_and_bad_ports_are_rejected(self):
        for port, lab in [(80, LAB), (8090, '../test'), (True, LAB)]:
            with self.assertRaises(ValueError): WorkerClient(port, lab)

    def test_missing_approval_extra_fields_and_shell_actions_never_contact_worker(self):
        client = WorkerClient(8090, LAB)
        with patch.object(client, 'request') as request:
            for name, arguments in [('android_create', {}), ('android_create', {'approved': False}), ('android_power', {'device_id': DEVICE, 'action': 'shell', 'approved': True}), ('devices_list', {'url': 'https://example.test'}), ('device_screenshot', {'device_id': 'emulator-5556'})]:
                with self.assertRaises(ValueError): client.call(name, arguments)
            request.assert_not_called()

    def test_power_is_scoped_to_configured_workspace_and_explicit_device(self):
        client = WorkerClient(8090, LAB)
        with patch.object(client, 'request', return_value={'ok': True}) as request:
            result = client.call('android_power', {'device_id': DEVICE, 'action': 'stop', 'approved': True})
        self.assertFalse(result['isError'])
        sent = request.call_args.args[1]
        self.assertEqual((sent['workspace_id'], sent['device_id'], sent['action']), (LAB, DEVICE, 'stop'))

    def test_png_is_returned_as_image_content_not_text_or_filesystem_path(self):
        client = WorkerClient(8090, LAB)
        with patch.object(client, 'request', return_value=b'\x89PNG\r\n\x1a\nfixture'):
            result = client.call('device_screenshot', {'device_id': DEVICE})
        self.assertEqual(result['content'][0]['type'], 'image')
        self.assertEqual(result['content'][0]['mimeType'], 'image/png')

    def test_errors_do_not_echo_worker_urls_or_sensitive_payloads(self):
        client = Mock(); client.call.side_effect = ValueError('sensitive-payload')
        server = Server(client); server.initialized = True
        result = server.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'devices_list'}})
        self.assertTrue(result['result']['isError']); self.assertNotIn('sensitive-payload', json.dumps(result))

    def test_local_http_redirects_never_forward_session_authority(self):
        with self.assertRaises(ValueError): NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.test/')

    def test_agent_can_choose_root_profile_without_changing_primary(self):
        client=WorkerClient(8090,LAB)
        with patch.object(client,'request',return_value={'ok':True}) as request:
            client.call('android_create',{'approved':True,'root_mode':'root'})
        self.assertEqual(request.call_args.args[1]['root_mode'],'root')

    def test_agent_ios_create_uses_explicit_model_and_runtime(self):
        client=WorkerClient(8090,LAB)
        with patch.object(client,'request',return_value={'ok':True}) as request:
            client.call('ios_create',{'approved':True,'runtime':'selected-runtime','model':'selected-model'})
        payload=request.call_args.args[1]
        self.assertEqual((payload['platform'],payload['runtime'],payload['model']),('ios','selected-runtime','selected-model'))

    def test_reverse_requires_exact_identity_and_explicit_inspection_approval(self):
        client=WorkerClient(8090,LAB)
        identity={'package_id':'br.com.huntmob.demo','run_id':'a'*32,'sha256':'b'*64}
        with patch.object(client,'request',return_value={'ok':True}) as request:
            with self.assertRaises(ValueError):client.call('reverse_inspect',{**identity,'operation':'package','approved':False})
            request.assert_not_called()
            client.call('reverse_inspect',{**identity,'operation':'package','approved':True})
            self.assertEqual(request.call_args.args[1]['workspace_id'],LAB)
