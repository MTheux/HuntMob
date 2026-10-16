import http.client
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
from huntmob.remote_access import Gateway,matches,serve_remote

class Upstream(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_GET(self):
  if self.path=='/stream':
   self.send_response(200);self.send_header('Content-Type','application/octet-stream');self.end_headers()
   self.wfile.write(b'first-frame');self.wfile.flush()
   self.server.finish_stream.wait(3)
   return
  data=b'{"ok":true}'
  self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
 def do_POST(self):
  data=self.rfile.read(int(self.headers['Content-Length']))
  self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)

class GatewayTests(unittest.TestCase):
 def setUp(self):
  self.worker=ThreadingHTTPServer(('127.0.0.1',0),Upstream)
  self.worker.finish_stream=threading.Event()
  self.gateway=ThreadingHTTPServer(('127.0.0.1',0),Gateway)
  self.gateway.owner='owner@example.test';self.gateway.origin='https://worker.example.ts.net:8443';self.gateway.worker_port=self.worker.server_port
  for server in [self.worker,self.gateway]:threading.Thread(target=server.serve_forever,daemon=True).start()
 def tearDown(self):
  self.worker.finish_stream.set()
  for server in [self.gateway,self.worker]:server.shutdown();server.server_close()
 def request(self,path='/',headers=None,method='GET',body=None):
  connection=http.client.HTTPConnection('127.0.0.1',self.gateway.server_port,timeout=3)
  try:
   connection.request(method,path,body,headers or {});response=connection.getresponse();return response.status,response.read()
  finally:connection.close()
 def test_identity_missing_or_other_owner_cannot_read_screen_or_session(self):
  for path in ['/api/session','/api/device/video','/api/evidence','/']:
   for headers in [{},{'Tailscale-User-Login':'other@example.test'}]:self.assertEqual(self.request(path,headers)[0],403)
 def test_owner_can_proxy_local_worker_and_see_private_status(self):
  headers={'Tailscale-User-Login':self.gateway.owner}
  self.assertEqual(self.request('/',headers)[1],b'{"ok":true}')
  self.assertTrue(json.loads(self.request('/api/remote/status',headers)[1])['owner_only'])
 def test_post_requires_remote_same_origin_and_preserves_body(self):
  headers={'Tailscale-User-Login':self.gateway.owner}
  self.assertEqual(self.request('/',headers,'POST',b'owned')[0],403)
  headers['Origin']=self.gateway.origin
  self.assertEqual(self.request('/',headers,'POST',b'owned'),(200,b'owned'))
 def test_video_bytes_forwarded_without_waiting_for_stream_to_end(self):
  connection=http.client.HTTPConnection('127.0.0.1',self.gateway.server_port,timeout=1)
  try:
   connection.request('GET','/stream',headers={'Tailscale-User-Login':self.gateway.owner})
   response=connection.getresponse()
   self.assertEqual(response.read(11),b'first-frame')
   self.assertFalse(self.worker.finish_stream.is_set())
  finally:self.worker.finish_stream.set();connection.close()
 def test_no_arbitrary_proxy_target(self):
  self.assertEqual(self.request('http://outside.test/',{'Tailscale-User-Login':self.gateway.owner})[0],400)
 def test_existing_tailnet_service_never_mutated(self):
  with patch('huntmob.remote_access.identity',return_value=('owner','worker.example.ts.net')),patch('huntmob.remote_access.configuration',return_value={'TCP':{'8443':{'HTTPS':True}}}),patch('huntmob.remote_access.ts') as command:
   with self.assertRaisesRegex(ValueError,'já configurada'):serve_remote()
   command.assert_not_called()
 def test_funnel_and_different_target_not_owned(self):
  config={'TCP':{'8443':{'HTTPS':True}},'Web':{'worker.example.ts.net:8443':{'Handlers':{'/':{'Proxy':'http://127.0.0.1:8091'}}}}}
  self.assertTrue(matches(config,'worker.example.ts.net',8443,8091))
  config['AllowFunnel']={'worker.example.ts.net:8443':True}
  self.assertFalse(matches(config,'worker.example.ts.net',8443,8091))
