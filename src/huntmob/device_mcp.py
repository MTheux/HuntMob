"""Local stdio MCP adapter for a single HuntMob device workspace.

Device management and explicit offline inspections of the selected APK only.
Uses the running worker API so UI and agents share the same device registry.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path
from http.cookiejar import CookieJar
from urllib.parse import urlsplit, parse_qs
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler, HTTPCookieProcessor

from .lab_sessions import LAB_NAME

PROTOCOL = '2025-03-26'


def schema(properties=None, required=None):
    return {'type': 'object', 'properties': properties or {}, 'required': required or [], 'additionalProperties': False}


DEVICE = {'type': 'string', 'description': 'Explicit HuntMob device ID from devices_list.'}
APPROVED = {'type': 'boolean', 'const': True, 'description': 'The user authorized this requested action.'}
TOOLS = [
    {'name': 'devices_list', 'description': 'List the primary and companion Android/iOS devices in this workspace.', 'inputSchema': schema(), 'annotations': {'readOnlyHint': True}},
    {'name': 'device_screenshot', 'description': 'Capture one explicitly identified device as PNG.', 'inputSchema': schema({'device_id': DEVICE}, ['device_id']), 'annotations': {'readOnlyHint': True}},
    {'name': 'android_create', 'description': 'Create a clean Android companion. Optionally choose root AOSP or stock Google Play independently; keep existing devices running.', 'inputSchema': schema({'approved': APPROVED,'root_mode':{'type':'string','enum':['root','stock']}}, ['approved']), 'annotations': {'destructiveHint': False, 'idempotentHint': False}},
    {'name': 'android_power', 'description': 'Start or stop one companion. Stop preserves its data. Does not manage the primary.', 'inputSchema': schema({'device_id': DEVICE, 'action': {'type': 'string', 'enum': ['start', 'stop']}, 'approved': APPROVED}, ['device_id', 'action', 'approved']), 'annotations': {'destructiveHint': False}},
    {'name':'ios_catalog','description':'List installed iOS Simulator runtimes and iPhone model compatibility on this worker.','inputSchema':schema(),'annotations':{'readOnlyHint':True}},
    {'name':'ios_create','description':'Create a separate iPhone Simulator using an installed runtime and compatible model, alongside existing devices.','inputSchema':schema({'runtime':{'type':'string'},'model':{'type':'string'},'approved':APPROVED},['runtime','model','approved']),'annotations':{'destructiveHint':False,'idempotentHint':False}},
    {'name':'device_power','description':'Start or stop one explicitly identified companion Android or iPhone; preserve data.','inputSchema':schema({'device_id':DEVICE,'action':{'type':'string','enum':['start','stop']},'approved':APPROVED},['device_id','action','approved']),'annotations':{'destructiveHint':False}},
    {'name':'reverse_context','description':'Read selected APK identity, decompilation metadata, REA evidence and Companion brief. Does not run a model or app.','inputSchema':schema({'package_id':{'type':'string'},'run_id':{'type':'string'},'sha256':{'type':'string'}},['package_id','run_id','sha256']),'annotations':{'readOnlyHint':True}},
    {'name':'reverse_target','description':'Discover the selected package, exact decompilation run and APK SHA256 in this configured workspace.','inputSchema':schema(),'annotations':{'readOnlyHint':True}},
    {'name':'reverse_inspect','description':'Explicit bounded offline REA inspection of the selected APK. Never launches the app or contacts its backend.','inputSchema':schema({'package_id':{'type':'string'},'run_id':{'type':'string'},'sha256':{'type':'string'},'operation':{'type':'string','enum':['package','classes','class','method','references']},'query':{'type':'string'},'class_name':{'type':'string'},'method_name':{'type':'string'},'overload_index':{'type':'integer','minimum':0},'approved':APPROVED},['package_id','run_id','sha256','operation','approved']),'annotations':{'destructiveHint':False}},
    {'name':'reverse_jobs','description':'Read exact-run offline REA job state and Evidence after reverse_inspect.','inputSchema':schema({'package_id':{'type':'string'},'run_id':{'type':'string'},'sha256':{'type':'string'}},['package_id','run_id','sha256']),'annotations':{'readOnlyHint':True}},
]
TOOLS.append({'name':'reverse_record_review','description':'Record an attributed static architecture review from your Companion investigation. Observations must cite Evidence IDs returned by this run. Always marked needs_review, never independently verified.','inputSchema':schema({'package_id':{'type':'string'},'run_id':{'type':'string'},'sha256':{'type':'string'},'approved':APPROVED,'report':{'type':'object','properties':{'summary':{'type':'string','maxLength':4000},'observations':{'type':'array','maxItems':20,'items':schema({'text':{'type':'string'},'evidence_id':{'type':'string'}},['text','evidence_id'])},'inferences':{'type':'array','items':{'type':'string'}},'unknowns':{'type':'array','items':{'type':'string'}}},'required':['summary'],'additionalProperties':False}},['package_id','run_id','sha256','report','approved']),'annotations':{'destructiveHint':False}})


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Worker redirect refused')


class WorkerClient:
    def __init__(self, port, workspace):
        if type(port) is not int or not 1024 <= port <= 65535 or not LAB_NAME.fullmatch(workspace):
            raise ValueError('Invalid local worker or workspace')
        self.origin = f'http://127.0.0.1:{port}'
        self.workspace = workspace
        self.operator_proof = None
        self.opener = build_opener(ProxyHandler({}), NoRedirect(), HTTPCookieProcessor(CookieJar()))

    def _authenticate(self):
        path = Path.home() / '.huntmob/operator-access-url.txt'
        if path.is_symlink() or path.stat().st_size > 512:
            raise ValueError('Invalid local operator access file')
        import os, stat
        if os.name != 'nt' and (path.stat().st_uid != os.getuid() or stat.S_IMODE(path.stat().st_mode) & 0o077):
            raise ValueError('Operator access file must be owner-only')
        url = urlsplit(path.read_text().strip())
        if url.scheme + '://' + url.netloc != self.origin or url.path != '/' or url.query:
            raise ValueError('Operator access file belongs to a different worker')
        tokens = parse_qs(url.fragment).get('operator', [])
        if len(tokens) != 1 or len(tokens[0]) != 64:
            raise ValueError('Invalid operator access value')
        request = Request(self.origin + '/api/auth/bootstrap', data=json.dumps({'token': tokens[0]}).encode(), headers={'Content-Type':'application/json', 'Origin':self.origin})
        with self.opener.open(request, timeout=5) as response:
            data = json.loads(response.read(1024))
            if response.status != 200 or not data.get('authenticated') or not data.get('proof'):
                raise ValueError('Operator bootstrap was refused')
            self.operator_proof = data['proof']

    def request(self, path, payload=None, _retried=False):
        if not path.startswith(('/api/workspace/', '/api/session', '/api/reverse/')) and path!='/api/ios/catalog':
            raise ValueError('Unknown worker operation')
        headers = {}
        if payload is not None:
            token = self.request('/api/session')['csrf_token']
            headers = {'Content-Type': 'application/json', 'X-HuntMob-CSRF': token}
        if self.operator_proof:
            headers['X-HuntMob-Operator'] = self.operator_proof
        request = Request(self.origin + path, data=json.dumps(payload).encode() if payload is not None else None, headers=headers)
        try:
            with self.opener.open(request, timeout=240 if payload else 15) as response:
                data = response.read(8 * 1024 * 1024 + 1)
                if len(data) > 8 * 1024 * 1024:
                    raise ValueError('Worker response exceeds limit')
                return data if response.headers.get_content_type() == 'image/png' else json.loads(data)
        except HTTPError as error:
            if error.code == 401 and not _retried:
                error.close()
                try: self._authenticate()
                except (OSError, ValueError): raise ValueError('Conecte o operador no launcher local antes de usar o agente.') from None
                return self.request(path, payload, _retried=True)
            error.close()
            raise ValueError('Worker refused the device operation. Refresh devices_list.') from None

    def call(self, name, arguments):
        spec = next((item for item in TOOLS if item['name'] == name), None)
        if spec is None or not isinstance(arguments, dict):
            raise ValueError('Unknown tool or invalid arguments')
        shape = spec['inputSchema']
        if set(arguments) - set(shape['properties']) or any(key not in arguments for key in shape['required']):
            raise ValueError('Invalid tool arguments')
        if 'device_id' in arguments and (not isinstance(arguments['device_id'], str) or not LAB_NAME.fullmatch(arguments['device_id'])):
            raise ValueError('Invalid device identity')
        if name in {'android_create', 'android_power','ios_create','device_power'} and arguments.get('approved') is not True:
            raise ValueError('User approval is required for device lifecycle actions')
        if name == 'devices_list':
            result = self.request('/api/workspace/devices?' + urlencode({'workspace': self.workspace}))
        elif name == 'reverse_target':
            result = self.request('/api/reverse/target?' + urlencode({'workspace': self.workspace}))
        elif name in {'reverse_context','reverse_jobs','reverse_inspect','reverse_record_review'}:
            from .reverse_workspace import PACKAGE, RUN
            import re
            if not isinstance(arguments.get('package_id'),str) or not PACKAGE.fullmatch(arguments['package_id']) or not isinstance(arguments.get('run_id'),str) or not RUN.fullmatch(arguments['run_id']) or not isinstance(arguments.get('sha256'),str) or not re.fullmatch('[a-f0-9]{64}',arguments['sha256']):
                raise ValueError('Explicit package, run and SHA256 are required')
            if name in {'reverse_inspect','reverse_record_review'}:
                if arguments.get('approved') is not True:raise ValueError('User approval is required for inspection')
                result=self.request('/api/reverse/'+('inspect' if name=='reverse_inspect' else 'review'),{**arguments,'workspace_id':self.workspace,'authorized':True})
            else:
                query=urlencode({'workspace':self.workspace,'package':arguments['package_id'],'run':arguments['run_id'],'sha256':arguments['sha256']})
                result=self.request('/api/reverse/'+('companion' if name=='reverse_context' else 'inspections')+'?'+query)
        elif name=='ios_catalog':
            result=self.request('/api/ios/catalog')
        elif name == 'device_screenshot':
            png = self.request('/api/workspace/device/screenshot?' + urlencode({'workspace': self.workspace, 'device': arguments['device_id']}))
            if not isinstance(png, bytes) or not png.startswith(b'\x89PNG\r\n\x1a\n'):
                raise ValueError('Device screenshot unavailable')
            return {'content': [{'type': 'image', 'mimeType': 'image/png', 'data': base64.b64encode(png).decode()}]}
        else:
            action = 'create' if name in {'android_create','ios_create'} else arguments['action']
            if action not in {'create', 'start', 'stop'}:
                raise ValueError('Unknown device lifecycle action')
            payload={'action':action,'workspace_id':self.workspace,'device_id':arguments.get('device_id'),'authorized':True,'approved':True}
            if name=='android_create' and 'root_mode' in arguments:
                if arguments['root_mode'] not in {'root','stock'}:raise ValueError('Invalid Android profile')
                payload['root_mode']=arguments['root_mode']
            if name=='ios_create':payload.update(platform='ios',runtime=arguments['runtime'],model=arguments['model'])
            result = self.request('/api/workspace/device/action', payload)
        return {'content': [{'type': 'text', 'text': json.dumps(result, ensure_ascii=False)}], 'isError': result.get('ok') is False}


class Server:
    def __init__(self, client):
        self.client = client
        self.initialized = False

    def handle(self, message):
        if not isinstance(message, dict) or message.get('jsonrpc') != '2.0' or not isinstance(message.get('method'), str):
            return {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32600, 'message': 'Invalid request'}}
        if 'id' not in message:
            return None
        response = {'jsonrpc': '2.0', 'id': message['id']}
        method, params = message['method'], message.get('params', {})
        if not isinstance(params, dict):
            return {**response, 'error': {'code': -32602, 'message': 'Invalid params'}}
        if method == 'initialize':
            self.initialized = True
            version = params.get('protocolVersion')
            response['result'] = {'protocolVersion': version if version in {PROTOCOL, '2024-11-05'} else PROTOCOL,
                                  'capabilities': {'tools': {'listChanged': False}}, 'serverInfo': {'name': 'huntmob-devices', 'version': '0.1.0'}}
        elif method == 'ping':
            response['result'] = {}
        elif not self.initialized:
            response['error'] = {'code': -32002, 'message': 'Initialize first'}
        elif method == 'tools/list':
            response['result'] = {'tools': TOOLS}
        elif method == 'tools/call':
            try:
                response['result'] = self.client.call(params.get('name'), params.get('arguments', {}))
            except (OSError, ValueError, KeyError, TypeError):
                response['result'] = {'content': [{'type': 'text', 'text': 'Device operation unavailable or invalid. Check identity, state and approval.'}], 'isError': True}
        else:
            response['error'] = {'code': -32601, 'message': 'Method not found'}
        return response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8090)
    parser.add_argument('--workspace', required=True)
    args = parser.parse_args()
    server = Server(WorkerClient(args.port, args.workspace))
    while True:
        line = sys.stdin.buffer.readline(65537)
        if not line:
            break
        if len(line) > 65536:
            break
        try:
            message = json.loads(line)
            if isinstance(message, list) and 0 < len(message) <= 16:
                responses = [item for item in (server.handle(request) for request in message) if item is not None]
                result = responses or None
            else:
                result = server.handle(message)
        except (ValueError, TypeError):
            result = {'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'Parse error'}}
        if result is not None:
            sys.stdout.write(json.dumps(result, ensure_ascii=False) + '\n')
            sys.stdout.flush()


if __name__ == '__main__':
    main()
