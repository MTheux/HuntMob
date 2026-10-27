"""Private Tailscale Serve gateway to the existing local HuntMob worker.

Trust identity headers only on loopback behind Tailscale Serve, which removes
client-supplied identity headers. Never enables Funnel or changes tailnet ACLs.
"""
import http.client
import json
import re
import shutil
import signal
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

HOP = {'connection','transfer-encoding','keep-alive','proxy-authorization','proxy-authenticate','te','trailer','upgrade'}


def ts(*args):
    executable=shutil.which('tailscale')
    if not executable:raise ValueError('Tailscale não instalado no worker.')
    try:
        result=subprocess.run([executable,*args],capture_output=True,text=True,stdin=subprocess.DEVNULL,timeout=15)
    except subprocess.TimeoutExpired as error:
        output=error.stdout.decode(errors='replace') if isinstance(error.stdout,bytes) else (error.stdout or '')
        link=re.search(r'https://login\.tailscale\.com/f/serve\?node=[A-Za-z0-9_-]+',output)
        if link:raise ValueError('Serve exige liberação pelo proprietário da conta Tailscale: '+link[0]) from error
        raise ValueError('Tailscale excedeu o tempo de resposta. Nenhum acesso remoto foi confirmado.') from error
    if result.returncode:raise ValueError('Tailscale recusou a configuração. Verifique login e HTTPS habilitado no tailnet.')
    return result.stdout


def configuration():return json.loads(ts('serve','status','--json') or '{}')


def identity():
    status=json.loads(ts('status','--json'))
    own=status.get('Self',{})
    login=status.get('User',{}).get(str(own.get('UserID')),{}).get('LoginName')
    dns=own.get('DNSName','').rstrip('.')
    if status.get('BackendState')!='Running' or not login or not re.fullmatch(r'[a-zA-Z0-9.-]+\.ts\.net',dns):
        raise ValueError('Worker precisa estar conectado ao Tailscale com identidade de usuário e MagicDNS.')
    return login,dns


def matches(config,dns,https_port,gateway_port):
    endpoint=f'{dns}:{https_port}'
    handlers=config.get('Web',{}).get(endpoint,{}).get('Handlers',{})
    return config.get('TCP',{}).get(str(https_port),{}).get('HTTPS') is True and handlers=={'/':{'Proxy':f'http://127.0.0.1:{gateway_port}'}} and not config.get('AllowFunnel',{}).get(endpoint,False)


class Gateway(BaseHTTPRequestHandler):
    def log_message(self,*args):pass  # No identities, query secrets or captured data in logs.

    def forward(self):
        users=self.headers.get_all('Tailscale-User-Login') or []
        if users != [self.server.owner]:
            self.send_error(403,'Acesso restrito ao proprietario do worker no Tailscale.');return
        if self.command not in {'GET','HEAD','POST'}:
            self.send_error(405);return
        if not self.path.startswith('/') or self.path.startswith('//'):
            self.send_error(400);return
        if self.command=='POST' and self.headers.get('Origin')!=self.server.origin:
            self.send_error(403,'Origem remota invalida.');return
        if self.headers.get('Transfer-Encoding'):
            self.send_error(400,'Envio chunked nao suportado.');return
        lengths=self.headers.get_all('Content-Length') or ['0']
        try:
            if len(lengths)!=1:raise ValueError()
            length=int(lengths[0])
            if not 0<=length<=512*1024*1024:raise ValueError()
        except ValueError:self.send_error(413);return
        if self.path=='/api/remote/status' and self.command=='GET':
            data=json.dumps({'active':True,'transport':'tailscale-https','owner_only':True,'url':self.server.origin}).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data);return
        connection=http.client.HTTPConnection('127.0.0.1',self.server.worker_port,timeout=240)
        responded=False
        try:
            headers={k:v for k,v in self.headers.items() if k.lower() not in HOP|{'host','content-length','expect'} and not k.lower().startswith('tailscale-')}
            headers['Host']=f'127.0.0.1:{self.server.worker_port}'
            # The remote origin/owner were checked above. Upstream remains a
            # separate loopback origin, with operator cookie authentication.
            headers['Origin']=f'http://127.0.0.1:{self.server.worker_port}'
            headers['Connection']='close'
            if self.command=='POST':headers['Content-Length']=str(length)
            connection.putrequest(self.command,self.path,skip_host=True,skip_accept_encoding=True)
            for key,value in headers.items():connection.putheader(key,value)
            connection.endheaders()
            remaining=length
            while remaining:
                chunk=self.rfile.read(min(65536,remaining))
                if not chunk:raise OSError('Upload interrupted')
                connection.send(chunk);remaining-=len(chunk)
            response=connection.getresponse();self.send_response(response.status);responded=True
            for key,value in response.getheaders():
                if key.lower() not in HOP:self.send_header(key,value + '; Secure' if key.lower()=='set-cookie' and '; secure' not in value.lower() else value)
            if not response.getheader('Cache-Control'):self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff');self.end_headers()
            if self.command!='HEAD':
                while True:
                    chunk=response.read1(65536)
                    if not chunk:break
                    self.wfile.write(chunk);self.wfile.flush()
        except (OSError,http.client.HTTPException):
            if not responded:self.send_error(502,'Worker HuntMob indisponivel.');
        finally:connection.close();self.close_connection=True

    do_GET=do_HEAD=do_POST=forward
    do_PUT=do_DELETE=forward


def serve_remote(worker_port=8090,gateway_port=8091,https_port=8443):
    for port in (worker_port,gateway_port,https_port):
        if type(port) is not int or not 1<=port<=65535:raise ValueError('Porta inválida.')
    if len({worker_port,gateway_port,https_port})!=3:raise ValueError('Use portas distintas para worker, gateway e HTTPS.')
    owner,dns=identity();config=configuration()
    if str(https_port) in config.get('TCP',{}) or f'{dns}:{https_port}' in config.get('Web',{}) or f'{dns}:{https_port}' in config.get('AllowFunnel',{}):
        raise ValueError('Porta Tailscale já configurada; o serviço existente não será alterado.')
    probe=http.client.HTTPConnection('127.0.0.1',worker_port,timeout=5)
    try:
        probe.request('GET','/api/client/ping');response=probe.getresponse()
        if response.status!=200 or json.loads(response.read(4096)).get('ok') is not True:raise ValueError('Inicie a UI local do HuntMob primeiro.')
    finally:probe.close()
    with ThreadingHTTPServer(('127.0.0.1',gateway_port),Gateway) as server:
        server.owner=owner;server.worker_port=worker_port;server.origin=f'https://{dns}:{https_port}'
        def terminate(*_):raise KeyboardInterrupt
        previous=signal.signal(signal.SIGTERM,terminate)
        try:
            ts('serve','--bg',f'--https={https_port}',f'http://127.0.0.1:{gateway_port}')
            if not matches(configuration(),dns,https_port,gateway_port):raise ValueError('Rota privada HTTPS não foi confirmada.')
            print('HuntMob remoto: '+server.origin,flush=True)
            print('Somente sua identidade Tailscale. Ctrl+C encerra apenas esta rota.',flush=True)
            server.serve_forever()
        except KeyboardInterrupt:pass
        finally:
            signal.signal(signal.SIGTERM,previous)
            if matches(configuration(),dns,https_port,gateway_port):
                ts('serve',f'--https={https_port}','off')
