#!/usr/bin/env python3
"""Read-only local report for sharing runtime limitations with a tester."""
import json
import platform
from huntmob import ios_worker, ios_native_readiness
from huntmob.ios_identity import simulator_identity


def report():
    inventory = ios_worker.inventory()
    native = ios_native_readiness.snapshot()
    return {
        'version': 1,
        'worker_os': platform.system(),
        'simulator_state': inventory.get('state', 'unavailable'),
        'identity': simulator_identity(inventory.get('lab', {})),
        'native_runtime_ready': native['ready'],
        'native_runtime_state': native['state'],
        'native_runtime_reason': native['summary'],
        'windows_local_ios_validated': False,
        'windows_ssh_browser_access': 'implemented-not-validated-on-windows',
        'client_ipa_execution_validated': False,
    }


if __name__ == '__main__':
    print(json.dumps(report(), ensure_ascii=False, indent=2))
