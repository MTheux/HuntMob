"""Native evidence-led DAST analysis. Does not call an external scanner or execute traffic."""
import hashlib
import html
import json
import re
from collections import Counter
from datetime import datetime, timezone

from .dynamic_runtime import private_json
from .lab_sessions import current, root

MONITORS = {
    'tls-observe': 'TLS e trust managers',
    'biometric-monitor': 'Biometria',
    'root-detection-observe': 'Verificações de integridade',
    'webview-observe': 'WebView',
    'crypto-observe': 'Criptografia',
    'file-observe': 'Acesso a arquivos',
}


ASSESSMENTS = {
    'tls-observe': ('TLS e transporte', 'SSLContext, trust managers e tráfego HTTP capturado.', 'Exercite chamadas HTTPS. Pinning e validação de certificados exigem teste específico.'),
    'biometric-monitor': ('Autenticação biométrica', 'Chamadas a authenticate nas APIs BiometricPrompt e FingerprintManager.', 'Exercite reconhecimento, falha e cancelamento; confirme a decisão de autenticação no backend.'),
    'root-detection-observe': ('Integridade do dispositivo', 'Chamadas File.exists e nomes de indicadores conhecidos quando presentes. Outras consultas a arquivos também aparecem no monitor.', 'Revise como o app usa o resultado; uma consulta não prova bloqueio ou eficácia.'),
    'webview-observe': ('WebView e bridges', 'Navegação observada e registro de interfaces JavaScript.', 'Revise origem do conteúdo e métodos expostos; uma bridge isolada não confirma XSS.'),
    'crypto-observe': ('Criptografia', 'Algoritmos solicitados a APIs de Cipher e MessageDigest.', 'Revise finalidade e gerenciamento de chaves. Buffers e chaves não são coletados.'),
    'file-observe': ('Armazenamento', 'Chamadas de acesso a arquivos, sem caminhos privados ou conteúdo.', 'Revise permissões e proteção de dados em Arquivos. I/O não comprova exposição.'),
}


MANUAL_CHECKS = [
    {'id':'business-logic', 'title':'Lógica de negócio', 'state':'not_assessed', 'next_step':'Validar sequência dos fluxos, limites e decisões do backend com dados controlados.'},
    {'id':'authorization', 'title':'Autorização e isolamento de contas', 'state':'not_assessed', 'next_step':'Comparar permissões e recursos entre contas de teste autorizadas. O monitor não testa IDOR/BOLA.'},
    {'id':'session', 'title':'Login e ciclo de sessão', 'state':'not_assessed', 'next_step':'Validar expiração, logout, revogação, MFA e decisões do servidor; tráfego capturado não prova autenticação segura.'},
    {'id':'data-exposure', 'title':'Exposição de dados', 'state':'not_assessed', 'next_step':'Revisar respostas redigidas, permissões e arquivos do app. Este motor não lê conteúdo privado do sandbox.'},
    {'id':'input-validation', 'title':'Validação de entrada', 'state':'not_assessed', 'next_step':'Revisar entrada, processamento e destino. Esta sessão não executa fuzzing ou payloads de injeção.'},
    {'id':'configuration', 'title':'Configuração e componentes Android', 'state':'not_assessed', 'next_step':'Revisar Manifest, componentes exportados, permissões e configuração de rede na análise Reverse.'},
]


def analyze(source):
    receipt = source.get('receipt', {})
    events = source.get('events', [])
    flows = source.get('network', [])
    candidates = []
    observations = []
    selected = set(receipt.get('scripts', []))
    coverage = []
    for script, title in MONITORS.items():
        relevant = [event for event in events if event.get('script') == script]
        kinds = Counter(event.get('kind') for event in relevant)
        state = 'observed' if kinds['call'] else 'ready_not_exercised' if kinds['hook_ready'] else 'unavailable' if kinds['hook_unavailable'] else 'not_selected' if script not in selected else 'no_evidence'
        coverage.append({'id': script, 'title': title, 'state': state, 'calls': kinds['call'], 'hooks_ready': kinds['hook_ready'], 'hooks_unavailable': kinds['hook_unavailable']})

    def candidate(rule, title, severity, description, references, remediation):
        candidates.append({'id': 'cand_' + hashlib.sha256((receipt.get('id', '') + rule).encode()).hexdigest()[:20], 'rule_id': rule, 'title': title, 'severity': severity, 'confidence': 'observed_fact', 'finding_status': 'candidate_review_required', 'cwe': 'CWE-319' if rule.startswith('http-') else 'CWE-327' if rule.startswith('crypto-') else 'CWE-328', 'description': description, 'evidence': references, 'remediation': remediation})

    cleartext = []
    credential_http = []
    failed = []
    for flow in flows:
        if flow.get('scheme') == 'http':
            reference = {'kind': 'network', 'id': flow.get('id'), 'method': flow.get('method'), 'host': flow.get('host'), 'port': flow.get('port'), 'path': flow.get('path'), 'status': flow.get('status')}
            cleartext.append(reference)
            body = flow.get('request', {}).get('body', '')
            # Field presence is observable even when values have already been redacted.
            if (isinstance(body, str) and re.search(r'(?:^|[&\s{"\'])password(?:["\']?\s*[:=])', body, re.I)) or re.search(r'[?&]password=', flow.get('path', ''), re.I) or any(key.lower() == 'authorization' for key in flow.get('request', {}).get('headers', {})):
                credential_http.append(reference)
        if flow.get('state') == 'error': failed.append({'kind': 'network', 'id': flow.get('id')})
    if credential_http:
        candidate('http-credential-fields', 'Campos de autenticação em requisição HTTP', 'medium', 'O tráfego observado usa HTTP e contém um campo de senha ou um header de autenticação. Os valores foram mascarados. O impacto fora deste laboratório e as proteções adicionais precisam de revisão.', credential_http, 'Use HTTPS no endpoint e valide a configuração de rede do app. Confirme se esse fluxo também existe no build de produção.')
    elif cleartext:
        candidate('http-transport', 'Tráfego HTTP observado', 'low', 'Foram observadas requisições HTTP. Isso não demonstra, por si só, exposição de dados sensíveis; revise o contexto e o build utilizado.', cleartext, 'Revise o uso de cleartext e prefira HTTPS nos fluxos que transportam dados sensíveis.')
    if failed:
        observations.append({'title': 'Falhas de conexão', 'count': len(failed), 'evidence': failed, 'meaning': 'Problema operacional; não classificado como vulnerabilidade.'})
    algorithms = {}
    bridges = []
    integrity = []
    for index, event in enumerate(events):
        if event.get('kind') != 'call': continue
        reference = {'kind': 'frida', 'job_id': receipt.get('id'), 'event_index': index, 'at': event.get('at'), 'class_name': event.get('class_name'), 'method': event.get('method')}
        if event.get('algorithm'):
            algorithms.setdefault(event['algorithm'], []).append(reference)
        if event.get('script') == 'webview-observe' and event.get('method') == 'addJavascriptInterface': bridges.append(reference)
        if event.get('integrity_indicator') in {'su', 'busybox', 'magisk', 'Superuser.apk'}: integrity.append(reference)
    for algorithm, references in algorithms.items():
        upper = algorithm.upper()
        if '/ECB/' in upper:
            candidate('crypto-ecb-' + algorithm, 'Modo ECB observado', 'medium', f'Uma chamada de criptografia solicitou {algorithm}. O dado protegido e a aplicabilidade do risco precisam ser verificados; nenhuma chave ou buffer foi coletado.', references, 'Revise o fluxo e prefira um modo autenticado adequado ao caso de uso, com gerenciamento correto de nonce e chave.')
        elif upper in {'DES', 'DESEDE'} or upper.startswith(('DES/', 'DESEDE/')):
            candidate('crypto-legacy-' + algorithm, 'Algoritmo de criptografia legado observado', 'medium', f'A API recebeu {algorithm}. A finalidade e os dados envolvidos ainda precisam de revisão.', references, 'Planeje migração para um algoritmo e modo atuais adequados ao fluxo, preservando compatibilidade de dados quando necessária.')
        elif upper in {'MD5', 'SHA1', 'SHA-1'}:
            candidate('digest-legacy-' + algorithm, 'Digest legado observado', 'low', f'A API recebeu {algorithm}. Essa observação não identifica sua finalidade nem demonstra hashing de senhas.', references, 'Verifique a finalidade: use mecanismos atuais para integridade ou armazenamento de senhas conforme o caso de uso.')
        else:
            observations.append({'title': 'Algoritmo observado', 'algorithm': algorithm, 'count': len(references), 'evidence': references})
    if bridges: observations.append({'title': 'Bridge JavaScript registrada', 'count': len(bridges), 'evidence': bridges, 'meaning': 'Revise a origem do conteúdo carregado e os métodos expostos. A chamada isolada não confirma uma vulnerabilidade.'})
    if integrity: observations.append({'title': 'Indicadores de integridade consultados', 'count': len(integrity), 'evidence': integrity, 'meaning': 'Verificações observadas; sua eficácia não foi testada.'})
    source_digest = hashlib.sha256(json.dumps(source, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    checks = [{**item, 'title': ASSESSMENTS[item['id']][0], 'evaluated': ASSESSMENTS[item['id']][1], 'next_step': ASSESSMENTS[item['id']][2]} for item in coverage]
    for item in checks:
        methods = Counter((event.get('class_name', ''), event.get('method', '')) for event in events if event.get('script') == item['id'] and event.get('kind') == 'call')
        item['methods'] = [{'class_name': name, 'method': method, 'calls': count} for (name, method), count in methods.items()]
    network_summary = {'hosts': sorted({str(flow.get('host', '')) for flow in flows if flow.get('host')}), 'http': len(cleartext), 'https': sum(flow.get('scheme') == 'https' for flow in flows), 'connection_failures': len(failed), 'http_errors': sum(isinstance(flow.get('status'), int) and flow['status'] >= 400 for flow in flows)}
    return {'manual_checks': MANUAL_CHECKS, 'checks': checks, 'network_summary': network_summary, 'version': 1, 'engine': 'huntmob-native-dast', 'generated_at': datetime.now(timezone.utc).isoformat(), 'lab_id': receipt.get('lab_id'), 'job_id': receipt.get('id'), 'package_id': receipt.get('package_id'), 'apk_sha256': receipt.get('apk_sha256'), 'source_sha256': source_digest, 'session_state': receipt.get('state'), 'coverage': coverage, 'candidates': candidates, 'observations': observations, 'summary': {'events': len(events), 'network_requests': len(flows), 'screenshots': len(source.get('screenshots', [])), 'candidates': len(candidates), 'observed_monitors': sum(item['state'] == 'observed' for item in coverage)}, 'limitations': ['Análise limitada às chamadas, requisições e evidências desta sessão.', 'Monitor não exercitado não demonstra ausência de risco.', 'Pinning, autenticação, autorização e impacto de negócio não são validados automaticamente.', 'Este motor não executa fuzzing, exploitation ou bypass; candidatos exigem revisão.', 'A captura de rede pertence ao laboratório; atribuição exclusiva de cada requisição ao processo do app exige revisão.'], 'finding_status': 'not_assessed'}


def generate(runtime):
    source = json.loads(runtime.export())
    lab = runtime.context() if hasattr(runtime, 'context') else current()
    receipt = source.get('receipt', {})
    if receipt.get('lab_id') != lab.get('id') or receipt.get('apk_sha256') != lab.get('apk_sha256'):
        raise ValueError('Sessão não corresponde ao laboratório atual.')
    report = analyze(source)
    report['limitations'].extend(source.get('limitations', []))
    report['workspace_id'] = receipt.get('workspace_id', receipt.get('lab_id'))
    report['device_id'] = receipt.get('device_id', receipt.get('lab_id'))
    report['serial'] = receipt.get('serial')
    private_json(root() / lab['id'] / 'native-dast-report.json', report)
    return report


def latest(lab=None):
    lab = current() if lab is None else lab
    try:
        report = json.loads((root() / lab['id'] / 'native-dast-report.json').read_text())
        if report.get('lab_id') != lab['id'] or report.get('apk_sha256') != lab.get('apk_sha256'): raise ValueError('Report scope mismatch')
        return report
    except (OSError, ValueError, KeyError):
        return None


def render_html(report):
    escape = lambda value: html.escape(str(value))
    states = {'observed': 'Observado', 'ready_not_exercised': 'Pronto, não exercitado', 'unavailable': 'API indisponível', 'not_selected': 'Não selecionado', 'no_evidence': 'Sem evidência'}
    rows = ''.join(f'<tr><td>{escape(item["title"])}</td><td>{escape(states.get(item["state"],item["state"]))}</td><td>{item["calls"]}</td></tr>' for item in report['coverage'])
    candidates = ''.join('<article><h3>' + escape(item['title']) + '</h3><p>Candidato para revisão · ' + escape(item['severity']) + '</p><p>' + escape(item['description']) + '</p><p>' + escape(item['remediation']) + '</p><pre>' + escape(json.dumps(item['evidence'], indent=2, ensure_ascii=False)) + '</pre></article>' for item in report['candidates'])
    observations = ''.join('<article><h3>' + escape(item['title']) + '</h3><p>' + escape(item.get('meaning', item.get('algorithm', ''))) + '</p><pre>' + escape(json.dumps(item, ensure_ascii=False, indent=2)) + '</pre></article>' for item in report.get('observations', []))
    checks = ''.join('<article><h3>' + escape(item['title']) + '</h3><p>' + escape(item['evaluated']) + '</p><p>' + escape(item['next_step']) + '</p></article>' for item in report.get('checks', []))
    manual = ''.join('<article><h3>' + escape(item['title']) + ' · Não avaliado automaticamente</h3><p>' + escape(item['next_step']) + '</p></article>' for item in report.get('manual_checks', []))
    limitations = ''.join('<li>' + escape(value) + '</li>' for value in report['limitations'])
    return ('<!doctype html><html lang="pt-BR"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; img-src \'none\'"><title>HuntMob · relatório DAST</title><style>body{background:#0b0b0d;color:#eee;font:15px/1.6 system-ui;max-width:1100px;margin:40px auto;padding:24px}h1{color:#ef3158}table{width:100%;border-collapse:collapse}td,th{padding:12px;text-align:left;border-bottom:1px solid #333}article{border:1px solid #333;padding:20px;margin:20px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere}small,p{overflow-wrap:anywhere}</style><h1>HuntMob · relatório DAST nativo</h1><p>' + escape(report['package_id']) + '</p><small>APK SHA256: ' + escape(report['apk_sha256']) + '<br>Sessão: ' + escape(report['job_id']) + '<br>Gerado: ' + escape(report['generated_at']) + '<br>Fonte SHA256: ' + escape(report['source_sha256']) + '</small><h2>Cobertura observada</h2><table><thead><tr><th>Monitor</th><th>Estado</th><th>Chamadas</th></tr></thead><tbody>' + rows + '</tbody></table><h2>Candidatos para revisão</h2>' + (candidates or '<p>Nenhum candidato nas evidências analisadas. Isso não equivale a uma declaração de segurança do app.</p>') + '<h2>O que foi avaliado</h2>' + checks + '<h2>Observações</h2>' + (observations or '<p>Nenhuma observação adicional.</p>') + '<h2>Testes pendentes</h2>' + manual + '<h2>Limitações</h2><ul>' + limitations + '</ul></html>').encode()
