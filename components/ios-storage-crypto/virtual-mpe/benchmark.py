#!/usr/bin/env python3
"""Bounded PUBLIC-fixture timing of frozen core, not guest/boot/UI latency."""
import argparse
import hashlib
import json
import platform
import shlex
import subprocess
import tempfile
import time
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authorized-synthetic-benchmark',action='store_true',required=True)
    args=parser.parse_args()
    own=Path(__file__).resolve().parent
    project=own.parents[2]
    sources=[own/'crypto/huntmob-virtual-mpe.c',own/'include/crypto/huntmob-virtual-mpe.h',own/'benchmark.c',own/'benchmark.py',own/'benchmark_allocator.h']
    patch=project/'components/ios-engine/huntmob-virtual-mpe-core-v1.patch'
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    expected='1181c06df0185207e92f99db410d74d8d73dae043c3b1ab8ef6d33811311198d'
    if sha(patch)!=expected:raise ValueError('Frozen patch changed')
    before={str(p):sha(p) for p in sources}
    compiler=subprocess.check_output(['xcrun','--find','clang'],text=True).strip()
    version=subprocess.check_output([compiler,'--version'],text=True).splitlines()[0]
    cpu=subprocess.check_output(['/usr/sbin/sysctl','-n','machdep.cpu.brand_string'],text=True).strip()
    nettle=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','nettle'],text=True))
    flags=['-std=c11','-Wall','-Wextra','-Werror','-O2','-pthread','-DHUNTMOB_VIRTUAL_MPE_STANDALONE','-I'+str(own/'include')]
    with tempfile.TemporaryDirectory(prefix='huntmob-mpe-public-timing-') as directory:
        root=Path(directory);binary=root/'benchmark'
        obj=root/'core.o'
        allocator_flags=['-include',str(own/'benchmark_allocator.h'),'-Dmalloc=mpe_bench_malloc','-Dcalloc=mpe_bench_calloc','-Dfree=mpe_bench_free']
        subprocess.run([compiler]+flags+allocator_flags+['-c',str(sources[0]),'-o',str(obj)]+[f for f in nettle if f.startswith('-I')],check=True,capture_output=True)
        subprocess.run([compiler]+flags+[str(obj),str(own/'benchmark.c'),'-o',str(binary)]+nettle,check=True,capture_output=True)
        start=time.monotonic()
        result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=30)
        if result.returncode:raise RuntimeError(result.stderr.strip())
        elapsed=time.monotonic()-start
        measurement=json.loads(result.stdout)
        if measurement['max_rss_bytes']>=512*1024**2:raise ValueError('RSS limit exceeded')
        result_hash=sha(binary)
    if before!={str(p):sha(p) for p in sources} or sha(patch)!=expected:raise ValueError('Input changed during run')
    record={'schema':'huntmob.own-mpe-core-benchmark.v1','date':'2026-10-15',
      'compiler':{'path':compiler,'version':version,'flags':flags,'core_allocator_flags':allocator_flags,'nettle_link_flags':nettle},
      'host':{'platform':platform.platform(),'cpu':cpu},'inputs_sha256':{str(p.relative_to(project)):h for p,h in [(p,before[str(p)]) for p in sources]},
      'frozen_patch_sha256':expected,'binary_sha256':result_hash,'timeout_seconds':30,'child_alarm_seconds':28,
      'tracked_allocation_budget_bytes':512*1024**2,'child_elapsed_wall_s':elapsed,'measurement':measurement,
      'estimated_ns_per_active_write_call':measurement['write_wall_s']*1e9/measurement['write_calls'],
      'stderr_empty':not result.stderr,'public_fixtures_only':True,'candidate_modified':False,
      'limits':['Standalone core API only; no TCG/ROMD callback or guest CPU instruction timing',
                'No disk, Keychain or firmware access; this is not whole boot time or UI fluidity',
                'Single run on current host; no statistical performance guarantee',
                'Resident peak checked by getrusage below512MiB; explicit core/cache allocation budget512MiB; no ASAN instrumentation'],
      'native_ready':False,'guest_performance_validated':False}
    output=project/'artifacts/validation/ios-virtual-mpe-core-benchmark-v1-2026-10-15.json'
    if output.exists():raise ValueError('Preserve prior benchmark receipt')
    output.write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({'receipt':str(output.relative_to(project)),'receipt_sha256':sha(output),
      'primary_init_wall_s':measurement['primary_init_wall_s'],'secondary_init_wall_s':measurement['secondary_init_wall_s'],
      'write_1MiB_as_8B_wall_s':measurement['write_wall_s'],'write_calls':measurement['write_calls'],
      'ns_per_call':record['estimated_ns_per_active_write_call'],'max_rss_MiB':measurement['max_rss_bytes']/1024**2,
      'child_elapsed_wall_s':elapsed},indent=2))


if __name__=='__main__':main()
