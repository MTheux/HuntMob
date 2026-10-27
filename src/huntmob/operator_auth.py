"""Operator authentication independent of guest apps, CSRF and the worker bridge.

The private launch URL carries a bootstrap value in its fragment (never an HTTP
request URL). Only a bounded bootstrap POST can mint an HttpOnly operator cookie.
"""
import hashlib
import hmac
import html
from http.cookies import SimpleCookie, CookieError
import json
import os
from pathlib import Path
import secrets
import time
from urllib.parse import urlsplit, parse_qsl, urlencode

COOKIE = 'huntmob_operator'
MAX_AGE = 8 * 60 * 60


def local_key():
    folder = Path.home() / '.huntmob'
    if folder.is_symlink():
        raise ValueError('Private HuntMob folder cannot be a symlink')
    folder.mkdir(mode=0o700, exist_ok=True)
    folder.chmod(0o700)
    path = folder / 'operator.key'
    if path.is_symlink():
        raise ValueError('Operator key cannot be a symlink')
    try:
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as output:
            output.write(secrets.token_hex(32))
    except FileExistsError:
        pass
    path.chmod(0o600)
    key = path.read_text(encoding='ascii').strip()
    if len(key) != 64 or any(char not in '0123456789abcdef' for char in key):
        raise ValueError('Invalid local operator key')
    return key


class OperatorSession:
    def __init__(self, secret):
        self.key = secret.encode('ascii')
        self.bootstrap = hmac.new(self.key, b'huntmob-operator-bootstrap-v1', hashlib.sha256).hexdigest()
        self.session_expires = int(time.time()) + MAX_AGE

    def launch_url(self, origin):
        return origin + '/#operator=' + self.bootstrap

    def _signature(self, expires):
        return hmac.new(self.key, ('operator-cookie-v1:' + expires).encode('ascii'), hashlib.sha256).hexdigest()

    def cookie(self):
        # Reconnecting a second tab must not replace the cookie under an active
        # tab's per-origin proof. Rotate together only after the session expires.
        if self.session_expires <= int(time.time()):
            self.session_expires = int(time.time()) + MAX_AGE
        expires = str(self.session_expires)
        return expires + '.' + self._signature(expires)

    def authenticated(self, headers):
        values = headers.get_all('Cookie') or []
        if len(values) != 1 or values[0].count(COOKIE + '=') != 1:
            return False
        try:
            jar = SimpleCookie(); jar.load(values[0])
            value = jar[COOKIE].value
            expires, signature = value.split('.', 1)
            remaining = int(expires) - int(time.time())
            return 0 < remaining <= MAX_AGE and hmac.compare_digest(signature, self._signature(expires))
        except (CookieError, ValueError, KeyError, UnicodeError):
            return False

    def proof(self, cookie):
        return hmac.new(self.key, ('operator-proof-v1:' + cookie).encode('ascii'), hashlib.sha256).hexdigest()

    @staticmethod
    def _cookie_value(headers):
        jar = SimpleCookie(); jar.load(headers.get('Cookie', ''))
        return jar[COOKIE].value

    @staticmethod
    def _target(path):
        value = urlsplit(path)
        if value.scheme or value.netloc or not value.path.startswith('/api/') or value.fragment or len(path) > 4096:
            raise ValueError('Invalid API ticket path')
        pairs = [(key, item) for key, item in parse_qsl(value.query, keep_blank_values=True) if key != '_operator_ticket']
        return value.path + ('?' + urlencode(pairs) if pairs else '')

    def ticket(self, path, cookie):
        expires = str(int(time.time()) + 45)
        message = 'operator-read-v1:' + expires + ':' + self._target(path) + ':' + cookie
        return expires + '.' + hmac.new(self.key, message.encode('utf-8'), hashlib.sha256).hexdigest()

    def _ticket_valid(self, path, cookie):
        try:
            tickets = [value for key, value in parse_qsl(urlsplit(path).query) if key == '_operator_ticket']
            if len(tickets) != 1:
                return False
            expires, signature = tickets[0].split('.', 1)
            remaining = int(expires) - int(time.time())
            message = 'operator-read-v1:' + expires + ':' + self._target(path) + ':' + cookie
            return 0 < remaining <= 45 and hmac.compare_digest(signature, hmac.new(self.key, message.encode('utf-8'), hashlib.sha256).hexdigest())
        except (ValueError, UnicodeError):
            return False

    def handle(self, handler):
        """Return True only when normal routing may continue."""
        path = urlsplit(handler.path).path
        if not path.startswith('/api/') or path == '/api/client/ping':
            return True
        authenticated = self.authenticated(handler.headers)
        cookie_value = self._cookie_value(handler.headers) if authenticated else ''
        proofs = handler.headers.get_all('X-HuntMob-Operator') or []
        proven = authenticated and len(proofs) == 1 and hmac.compare_digest(proofs[0].encode('utf-8'), self.proof(cookie_value).encode('ascii'))
        if path == '/api/auth/status' and handler.command == 'GET':
            self._reply(handler, {'ok': True, 'authenticated': proven})
            return False
        if path == '/api/auth/bootstrap' and handler.command == 'POST':
            lengths = handler.headers.get_all('Content-Length') or []
            try:
                if handler.headers.get('Transfer-Encoding') or len(lengths) != 1 or not 1 <= int(lengths[0]) <= 512:
                    raise ValueError
                handler.connection.settimeout(5)
                body = json.loads(handler.rfile.read(int(lengths[0])))
                token = body.get('token')
                if not isinstance(token, str) or not hmac.compare_digest(token.encode('ascii'), self.bootstrap.encode('ascii')):
                    raise ValueError
            except (OSError, ValueError, TypeError, AttributeError, UnicodeError):
                self._reply(handler, {'ok': False, 'reason': 'Endereço de acesso local inválido.'}, 401)
                return False
            secure = urlsplit(handler.headers.get('Origin', '')).scheme == 'https'
            value = self.cookie()
            cookie = f'{COOKIE}={value}; Path=/api/; HttpOnly; SameSite=Strict; Max-Age={MAX_AGE}' + ('; Secure' if secure else '')
            self._reply(handler, {'ok': True, 'authenticated': True, 'proof': self.proof(value)}, cookie=cookie)
            return False
        if proven and path == '/api/auth/ticket' and handler.command == 'GET':
            try:
                paths = [value for key, value in parse_qsl(urlsplit(handler.path).query) if key == 'path']
                if len(paths) != 1 or paths[0].startswith(('/api/auth/', '/api/session')):
                    raise ValueError('Invalid download path')
                target = self._target(paths[0])
                self._reply(handler, {'ok': True, 'ticket': self.ticket(target, cookie_value)})
            except ValueError:
                self._reply(handler, {'ok': False, 'reason': 'Caminho de download inválido.'}, 400)
            return False
        read_ticket = (authenticated and handler.command == 'GET' and not path.startswith(('/api/auth/', '/api/session')) and self._ticket_valid(handler.path, cookie_value))
        if not proven and not read_ticket:
            self._reply(handler, {'ok': False, 'reason': 'Conecte a sessão do operador usando o endereço privado do launcher.', 'error_code': 'operator_session_required'}, 401)
            return False
        return True

    @staticmethod
    def _reply(handler, value, status=200, cookie=None):
        body = json.dumps(value).encode()
        handler.send_response(status)
        handler.send_header('Content-Type', 'application/json')
        handler.send_header('Cache-Control', 'no-store')
        handler.send_header('Content-Length', str(len(body)))
        if cookie:
            handler.send_header('Set-Cookie', cookie)
        handler.end_headers()
        handler.wfile.write(body)


def write_access_url(session, origin):
    folder = Path.home() / '.huntmob'
    folder.mkdir(mode=0o700, exist_ok=True)
    path = folder / 'operator-access-url.txt'
    if path.is_symlink():
        raise ValueError('Access URL file cannot be a symlink')
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as output:
        os.chmod(path, 0o600)
        output.write(session.launch_url(origin) + '\n')
    shortcut = folder / 'operator-access.html'
    if shortcut.is_symlink():
        raise ValueError('Access shortcut cannot be a symlink')
    with os.fdopen(os.open(shortcut, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as output:
        os.chmod(shortcut, 0o600)
        url = html.escape(session.launch_url(origin), quote=True)
        output.write(f'<!doctype html><meta name="referrer" content="no-referrer"><meta http-equiv="refresh" content="0;url={url}"><title>HuntMob local</title><a href="{url}">Conectar ao HuntMob local</a>')
    return path
