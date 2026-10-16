import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from huntmob.ui import HuntMobHandler, SESSION_TOKEN

LAB = 'huntmob_lab_' + 'a' * 32


class WorkspaceApiTests(unittest.TestCase):
    def setUp(self):
        class QuietHandler(HuntMobHandler):
            def log_message(self, *args): pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), QuietHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(2)

    def post(self, payload, token=None):
        headers = {'Content-Type': 'application/json'}
        if token is not None: headers['X-HuntMob-CSRF'] = token
        return urlopen(Request(self.base + '/api/workspace/device/action', data=json.dumps(payload).encode(), headers=headers), timeout=3)

    def test_csrf_and_approval_are_checked_before_device_management(self):
        with patch('huntmob.ui.workspace_devices.action') as action:
            for payload, token in [({'authorized': True, 'approved': True}, None), ({'authorized': True, 'approved': False}, SESSION_TOKEN)]:
                with self.assertRaises(HTTPError) as error: self.post(payload, token)
                self.assertEqual(error.exception.code, 403)
                error.exception.close()
            action.assert_not_called()

    def test_explicit_identity_reaches_only_workspace_dispatcher(self):
        payload = {'authorized': True, 'approved': True, 'action': 'create', 'workspace_id': LAB}
        with patch('huntmob.ui.workspace_devices.action', return_value={'ok': True}) as action:
            with self.post(payload, SESSION_TOKEN) as response: self.assertTrue(json.load(response)['ok'])
            action.assert_called_once_with(payload)

    def test_invalid_workspace_and_cross_workspace_screenshot_fail_closed(self):
        for route in ['/api/workspace/devices?workspace=../../bad', '/api/workspace/device/screenshot?workspace='+LAB+'&device=huntmob_lab_'+'b'*32]:
            with self.assertRaises(HTTPError) as error: urlopen(self.base + route, timeout=3)
            self.assertEqual(error.exception.code, 409); error.exception.close()

    def test_agent_config_is_bound_to_local_worker_and_workspace_without_token(self):
        with urlopen(self.base + '/api/workspace/agent?workspace=' + LAB, timeout=3) as response: data=json.load(response)
        config = data['config']['mcpServers']['huntmob-devices']
        self.assertIn(LAB, config['args']); self.assertIn(str(self.server.server_port), config['args'])
        self.assertNotIn(SESSION_TOKEN, json.dumps(config))

    def test_reverse_inspection_requires_csrf_and_explicit_approval(self):
        with patch('huntmob.ui.reverse_engines.start') as start:
            for payload,token in [({'authorized':True,'approved':True},None),({'authorized':True,'approved':False},SESSION_TOKEN)]:
                headers={'Content-Type':'application/json'}
                if token:headers['X-HuntMob-CSRF']=token
                for route in ('inspect','review','model-review'):
                    with self.assertRaises(HTTPError) as error:
                        urlopen(Request(self.base+'/api/reverse/'+route,data=json.dumps(payload).encode(),headers=headers),timeout=3)
                    self.assertEqual(error.exception.code,403);error.exception.close()
            start.assert_not_called()

    def test_reverse_context_does_not_cross_selected_workspace(self):
        with patch('huntmob.ui.reverse_engines.model_status',return_value={'model_connected':False}):
            with urlopen(self.base+'/api/reverse/engines',timeout=3) as response:
                self.assertFalse(json.load(response)['model_connected'])
        with self.assertRaises(HTTPError) as error:
            urlopen(self.base+'/api/reverse/target?workspace=wrong',timeout=3)
        self.assertEqual(error.exception.code,409);error.exception.close()

    def test_approved_local_model_request_reaches_only_model_dispatcher(self):
        payload={'authorized':True,'approved':True,'package_id':'br.com.huntmob.fixture','workspace_id':LAB,'run_id':'a'*32,'sha256':'b'*64}
        headers={'Content-Type':'application/json','X-HuntMob-CSRF':SESSION_TOKEN}
        with patch('huntmob.ui.reverse_engines.start_model_review',return_value={'ok':True,'state':'running'}) as start:
            request=Request(self.base+'/api/reverse/model-review',data=json.dumps(payload).encode(),headers=headers)
            with urlopen(request,timeout=3) as response: self.assertEqual(json.load(response)['state'],'running')
            start.assert_called_once_with(payload)
