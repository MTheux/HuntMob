#!/usr/bin/env python3
"""Native VirtualMPE own-model/public fixtures and independent Python AEAD oracle.
No engine, user backings, firmware, Keychain, networking or real roots accessed.
"""
import argparse
import ctypes as c
import hashlib
import hmac
import json
import os
import shlex
import subprocess
import tempfile
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--authorized-synthetic-selftest',action='store_true',required=True)
    args=parser.parse_args()
    own=Path(__file__).resolve().parent
    source=own/'crypto/huntmob-virtual-mpe.c'
    compiler=shlex.split(os.environ.get('CC','cc'))
    nettle=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','nettle'],text=True))
    base=compiler+['-std=c11','-Wall','-Wextra','-Werror','-O2','-pthread',
      '-DHUNTMOB_VIRTUAL_MPE_STANDALONE','-DHUNTMOB_VIRTUAL_MPE_TESTING','-I'+str(own/'include')]
    with tempfile.TemporaryDirectory(prefix='huntmob-virtual-mpe-public-') as directory:
        root=Path(directory);binary=root/'selftest';library=root/'core.so'
        subprocess.run(base+[str(source),str(own/'selftest.c'),'-o',str(binary)]+nettle,check=True)
        native=json.loads(subprocess.check_output([str(binary)],text=True))
        subprocess.run(base+['-shared','-fPIC',str(source),'-o',str(library)]+nettle,check=True)
        lib=c.CDLL(str(library));P=c.c_void_p;U=c.c_uint;Z=c.c_size_t;Q=c.c_uint64
        def fn(name,args,restype=c.c_bool):
            f=getattr(lib,'huntmob_virtual_mpe_'+name);f.argtypes=args;f.restype=restype;return f
        new=fn('new',[P,P,Q],P);free=fn('free',[P],None)
        bind=fn('bind_region',[P,U,Z,P]);stage=fn('stage_key',[P,U,P]);latch=fn('latch_key',[P,U])
        configure=fn('configure_region',[P,U,Q,Z]);initialize=fn('initialize_region',[P,U])
        record=fn('test_record',[P,U,Z,P,P,P]);replace=fn('test_replace',[P,U,Z,P,P,Q])
        read=fn('private_read',[P,U,Z,P,Z]);write=fn('private_write',[P,U,Z,P,Z])
        extread=fn('external_read',[P,U,Z,P,Z])
        checks=0
        def check(value):
            nonlocal checks
            checks+=1
            if not value:raise AssertionError('Independent public oracle mismatch')
        vm=bytes(range(16));salt=bytes(range(32,64));key0=bytes(range(64,96));key1=bytes(range(96,128))
        objects=[]
        def fixture(vid=vm,s=salt,epoch=1,baseaddr=0x100000):
            a=c.create_string_buffer(bytes(range(256)),256);b=c.create_string_buffer(bytes(reversed(range(256))),256)
            m=new(vid,s,epoch);check(m)
            check(bind(m,0,256,a));check(bind(m,1,256,b))
            check(stage(m,0,key0));check(latch(m,0));check(stage(m,1,key1));check(latch(m,1))
            check(configure(m,0,baseaddr,256));check(configure(m,1,0x200000,256))
            check(initialize(m,0));check(initialize(m,1));objects.append((m,a,b));return m,a,b
        def get(m,region,line):
            ct=c.create_string_buffer(64);tag=c.create_string_buffer(16);gen=Q()
            check(record(m,region,line,ct,tag,c.byref(gen)))
            return ct.raw,tag.raw,gen.value
        def expected(vid,s,epoch,region,physical,length,line,gen,plain):
            context=vid+s+epoch.to_bytes(8,'big')+region.to_bytes(4,'big')+physical.to_bytes(8,'big')+length.to_bytes(8,'big')
            material=(1).to_bytes(4,'big')+b'HuntMob.OwnMPE.v1/region\0'+context+(256).to_bytes(4,'big')
            key=hmac.new(key0+key1,material,hashlib.sha256).digest()
            nonce=line.to_bytes(4,'big')+gen.to_bytes(8,'big')
            aad=b'HuntMob.OwnMPE.v1/line\0'+context+line.to_bytes(4,'big')+gen.to_bytes(8,'big')+(64).to_bytes(4,'big')
            full=AESGCM(key).encrypt(nonce,plain,aad);return full[:64],full[64:]
        try:
            m,a,b=fixture()
            for region,cache,baseaddr in [(0,a,0x100000),(1,b,0x200000)]:
                for line in range(4):
                    ct,tag,gen=get(m,region,line)
                    ec,et=expected(vm,salt,1,region,baseaddr,256,line,gen,cache.raw[line*64:(line+1)*64])
                    check((ct,tag)==(ec,et));check(ct!=cache.raw[line*64:(line+1)*64])
            old=get(m,0,0)
            check(write(m,0,61,b'cross-line-write',16))
            for line in (0,1):
                ct,tag,gen=get(m,0,line)
                check((ct,tag)==expected(vm,salt,1,0,0x100000,256,line,gen,a.raw[line*64:(line+1)*64]))
            check(replace(m,0,0,old[0],old[1],old[2]))
            sentinel=c.create_string_buffer(b'\xa7'*128,128)
            check(not read(m,0,0,sentinel,128));check(sentinel.raw==b'\xa7'*128)
            # Full record transplantation must fail across line, region, VM,
            # salt, epoch and physical range; test-only injection is absent in QEMU.
            for variant in ('line','region','vm','salt','epoch','base'):
                m1,a1,b1=fixture()
                source_record=get(m1,0,0)
                destination=0;index=0;target=m1
                if variant=='line':index=1
                elif variant=='region':destination=1
                elif variant=='vm':target,_,_=fixture(vid=bytes(reversed(vm)))
                elif variant=='salt':target,_,_=fixture(s=bytes(reversed(salt)))
                elif variant=='epoch':target,_,_=fixture(epoch=2)
                elif variant=='base':target,_,_=fixture(baseaddr=0x300000)
                check(replace(target,destination,index,*source_record))
                sentinel=c.create_string_buffer(b'\xa7'*64,64)
                check(not extread(target,destination,index*64,sentinel,64));check(sentinel.raw==b'\xa7'*64)
        finally:
            for m,a,b in objects:
                free(m);check(a.raw==bytes(256));check(b.raw==bytes(256))
    print(json.dumps({'native':native,'independent_oracle_checks':checks,
      'public_fixtures_only':True,'nettle_version':subprocess.check_output(['pkg-config','--modversion','nettle'],text=True).strip(),
      'native_ready':False,'guest_mmio_validated':False,'apple_cipher_validated':False},indent=2))


if __name__=='__main__':main()
