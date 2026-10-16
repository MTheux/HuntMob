"""Identify only the capture process launched by this HuntMob worker."""
import json
import os
import shlex
import subprocess
from pathlib import Path


def receipt_path(port):
    return Path.home()/'.huntmob/run'/f'proxy-{port}.json'


def command_line(pid):
    if os.name=='nt':
        command=('powershell','-NoProfile','-NonInteractive','-Command',f'(Get-CimInstance Win32_Process -Filter "ProcessId={pid}").CommandLine')
    else:
        command=('ps','-p',str(pid),'-o','command=')
    result=subprocess.run(command,capture_output=True,text=True,timeout=3,check=False)
    return result.stdout.strip() if not result.returncode else ''


def owned(port):
    try:
        record=json.loads(receipt_path(port).read_text())
        pid=record['pid'];expected=record['command']
        if type(pid) is not int or pid<=0 or record['port']!=port or not isinstance(expected,list):return False
        # A PID alone is insufficient after restart: confirm the full argv,
        # including loopback binding, exact addon path and listener port.
        actual=[arg.strip('"') for arg in shlex.split(command_line(pid),posix=os.name!='nt')]
        return bool(expected) and len(actual)>=len(expected) and actual[-len(expected):]==expected
    except (OSError,ValueError,KeyError,TypeError,subprocess.TimeoutExpired):
        return False


def remember(port,process,command):
    from .dynamic_runtime import private_json
    private_json(receipt_path(port),{'pid':process.pid,'port':port,'command':list(command)})
