#!/usr/bin/env python3
"""Inventory a locally built experimental engine; never boots firmware."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    binary = args.binary.resolve(strict=True)
    result = {'schema': 1, 'engine': 'Inferno', 'binary': str(binary),
              'sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
              'firmware_boot_validated': False, 'ipa_execution_validated': False}
    for label, flag in [('version', '--version'), ('machines', '-machine'),
                        ('accelerators', '-accel')]:
        command = [str(binary), flag]
        if label != 'version':
            command.append('help')
        process = subprocess.run(command, capture_output=True, text=True, timeout=20)
        if process.returncode:
            raise SystemExit(f'Engine inventory failed: {label}')
        result[label] = process.stdout.strip()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'receipt': str(args.output), 'sha256': result['sha256'],
                      'firmware_boot_validated': False}))


if __name__ == '__main__':
    main()
