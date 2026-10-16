"""Read-only persistence audit; canary absence never proves Data Protection.

This validates one immutable evidence cohort, not an emulator's crypto engine.
Even matching hashes and no visible canary cannot promote runtime readiness.
"""
import hashlib
import json
import os
import re
import stat
from contextlib import contextmanager
from pathlib import Path

BACKINGS = tuple(f'namespace-{i}.raw' for i in range(1, 8)) + ('sep-nvram.raw', 'sep-ssc.raw')
CHUNK = 1024 * 1024


def _fingerprint(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _unchanged(path, initial):
    try:
        current = path.lstat()
    except OSError:
        return False
    return stat.S_ISREG(current.st_mode) and _fingerprint(current) == _fingerprint(initial)


@contextmanager
def _open_regular(path):
    """Bind reads to a regular file descriptor before consuming any contents."""
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode):
            raise ValueError('Arquivo de evidência ausente ou não regular.')
        flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ValueError('Arquivo de evidência indisponível para leitura segura.') from error
    with os.fdopen(descriptor, 'rb') as source:
        initial = os.fstat(source.fileno())
        if not stat.S_ISREG(initial.st_mode) or _fingerprint(before) != _fingerprint(initial) or not _unchanged(path, initial):
            raise ValueError('Arquivo de evidência alterado antes da leitura.')
        yield source, initial


def _read_bounded(path, limit):
    with _open_regular(path) as (source, initial):
        if initial.st_size > limit:
            raise ValueError('Arquivo de evidência excede o limite de leitura.')
        content = source.read(limit + 1)
        if len(content) > limit or _fingerprint(os.fstat(source.fileno())) != _fingerprint(initial) or not _unchanged(path, initial):
            raise ValueError('Arquivo de evidência alterado durante a leitura.')
    return content, initial


def validate_checkpoint(checkpoint):
    folder = Path(checkpoint).resolve(strict=True)
    evidence = {}
    proof_path = folder / 'protected-data-proof.json'
    raw_proof, evidence[proof_path] = _read_bounded(proof_path, 65536)
    try:
        proof = json.loads(raw_proof)
    except (ValueError, UnicodeError) as error:
        raise ValueError('Receipt de armazenamento inválido.') from error
    expected = proof.get('cohort_sha256') if isinstance(proof, dict) else None
    if not isinstance(expected, dict) or type(proof.get('version')) is not int or proof.get('version') != 1 or set(expected) != set(BACKINGS) or any(not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value) for value in expected.values()):
        raise ValueError('Conjunto completo de nove backings e hashes é obrigatório.')

    logs = sorted(folder.glob('disk-boot-*.log'))
    canaries = set()
    for path in logs:
        content, evidence[path] = _read_bounded(path, 8 * 1024 * 1024)
        canaries.update(re.findall(rb'Class C probe roundtrip completed; synthetic canary=([a-f0-9]{64})(?![a-f0-9])', content))
    if len(canaries) != 1:
        raise ValueError('Exatamente uma sonda sintética é necessária para esta validação.')
    canary = next(iter(canaries))
    results = []
    for name in BACKINGS:
        path = folder / name
        digest = hashlib.sha256()
        tail = b''
        found = False
        with _open_regular(path) as (source, initial):
            evidence[path] = initial
            for chunk in iter(lambda: source.read(CHUNK), b''):
                digest.update(chunk)
                window = tail + chunk
                if canary in window:
                    found = True
                tail = window[-(len(canary) - 1):]
            stable = _fingerprint(os.fstat(source.fileno())) == _fingerprint(initial) and _unchanged(path, initial)
        results.append({'name': name, 'size': initial.st_size, 'receipt_hash_matches': stable and digest.hexdigest() == expected[name], 'stable': stable, 'plaintext_canary_found': found})

    # Earlier files can change while later namespaces are being hashed.
    evidence_stable = all(_unchanged(path, initial) for path, initial in evidence.items())
    logs_unchanged = sorted(folder.glob('disk-boot-*.log')) == logs
    for item in results:
        item['stable'] = item['stable'] and _unchanged(folder / item['name'], evidence[folder / item['name']])
        item['receipt_hash_matches'] = item['receipt_hash_matches'] and item['stable']
    plaintext = any(item['plaintext_canary_found'] for item in results)
    matching = evidence_stable and logs_unchanged and all(item['receipt_hash_matches'] for item in results)
    if plaintext:
        reason = 'Conteúdo da sonda encontrado em claro no armazenamento persistido.'
    elif not matching:
        reason = 'Evidências alteradas ou hashes divergentes; o checkpoint não corresponde ao receipt.'
    else:
        reason = 'Ausência da sonda em claro não comprova criptografia, boot a frio ou classes sob bloqueio/desbloqueio.'
    return {'version': 1, 'ready': False, 'data_protection_validated': False, 'cohort_matches': matching, 'evidence_stable': evidence_stable and logs_unchanged, 'plaintext_canary_found': plaintext, 'state': 'failed' if plaintext or not matching else 'not_proven', 'backings': results, 'reason': reason}
