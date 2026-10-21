"""Shared, bounded H.264 relay and immediate input for the owned Android lab.

Wire protocol is pinned to scrcpy 5.0.1. No shell text or arbitrary target is accepted.
"""
import hashlib
import math
import select
import socket
import struct
import subprocess
import threading
import time
from pathlib import Path
from .android_worker import _run
from .lab_sessions import current
from .runtime_limits import MAX_CODEC_QUEUE_BYTES, MAX_STREAM_SECONDS, STREAM_STALL_SECONDS, stream_slot

VERSION='5.0.1'
DIGEST='764eb6f79811d5211fe9df341120882ba9994c7a61b897d7bf3fb662e53bc536'
SESSION=1 << 63
CONFIG=1 << 62
KEY=1 << 61
PORT=27184


def read_exact(connection, size):
    result=bytearray()
    while len(result)<size:
        chunk=connection.recv(size-len(result))
        if not chunk: raise OSError('Video connection closed')
        result.extend(chunk)
    return bytes(result)


def server_path():
    path=Path(__file__).resolve().parents[2]/'components/scrcpy'/('scrcpy-server-v'+VERSION+'.jar')
    if not path.is_file(): path=Path(__file__).parent/'_video'/('scrcpy-server-v'+VERSION+'.jar')
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=DIGEST:
        raise ValueError('Componente de vídeo ausente ou com hash divergente.')
    return path


class CodecRelay:
    def __init__(self, *, owner_check=None, forward_port=PORT):
        self.owner_check=owner_check or (lambda lab: lab==current().get('id'))
        self.forward_port=forward_port
        self.condition=threading.Condition()
        self.input_lock=threading.Lock()
        self.thread=None
        self.closing=threading.Event()
        self.control=None
        self.target=None
        self.packets=[]
        self.prefix=[]
        self.sequence=0
        self.config_sequence=0
        self.width=self.height=0
        self.error=''
        self.last_viewer=0
        self.frames=0
        self.started=0
        # Session generation invalidates delayed browser input after stop/restart.
        self.generation=1
        self.connection_attempts=0
        self.reconnect_count=0
        self.stall_count=0
        self.last_frame_at=0
        self.first_frame_ms=None
        self.queue_bytes=0

    def shutdown(self):
        self.closing.set()
        with self.condition: self.condition.notify_all()
        if self.thread: self.thread.join(4)

    def restart(self):
        self.shutdown()
        if self.thread and self.thread.is_alive(): raise RuntimeError('Previous video is still closing')
        with self.condition:
            self.closing.clear();self.thread=None;self.packets=[];self.prefix=[];self.error='';self.control=None;self.target=None;self.generation+=1;self.queue_bytes=0

    def get_packets(self, worker, after=None, timeout=8):
        lab=worker.avd_name
        if not worker.sdk or not self.owner_check(lab): raise ValueError('Laboratório de vídeo inválido.')
        target=(str(worker.sdk.adb),worker.serial,lab)
        with self.condition:
            if self.target and target!=self.target and self.thread and self.thread.is_alive(): raise ValueError('Aguarde o vídeo do laboratório anterior encerrar.')
            if self.closing.is_set(): raise RuntimeError('Video relay closing')
            self.last_viewer=time.monotonic()
            if not self.thread or not self.thread.is_alive():
                self.target=target;self.packets=[];self.prefix=[];self.error=''
                self.thread=threading.Thread(target=self._produce,args=(target,),daemon=True);self.thread.start()
            deadline=time.monotonic()+timeout
            while not self.packets or (after is not None and self.sequence<=after):
                if self.error: raise RuntimeError(self.error)
                if self.closing.is_set(): raise RuntimeError('Video relay closing')
                remaining=deadline-time.monotonic()
                if remaining<=0: return self.sequence,[]
                self.last_viewer=time.monotonic();self.condition.wait(min(remaining,1))
            # Rotation replaces the SPS and geometry even when no frame was
            # skipped. Existing viewers must receive that new decoder config.
            if after is None or after<self.config_sequence or after<self.packets[0][0]-1:
                return self.sequence,list(self.prefix)+[packet for _,packet in self.packets]
            return self.sequence,[packet for index,packet in self.packets if index>after]

    def snapshot(self):
        with self.condition:
            age=round(time.monotonic()-self.last_frame_at,3) if self.last_frame_at else None
            return {'transport':'h264-webcodecs','state':'error' if self.error else 'running' if self.control else 'idle','width':self.width,'height':self.height,'frames':self.frames,'error':self.error,'gop_packets':len(self.packets),'generation':self.generation,'input_ready':bool(self.control),
                    'telemetry':{'connection_attempts':self.connection_attempts,'reconnect_count':self.reconnect_count,'stall_count':self.stall_count,'first_frame_ms':self.first_frame_ms,'last_frame_age_seconds':age,'queue_bytes':self.queue_bytes,'queue_limit_bytes':MAX_CODEC_QUEUE_BYTES}}

    def input(self,payload):
        requested=payload.get('session_generation')
        if requested is not None and requested!=self.generation:
            return {'ok':False,'reason':'Sessão de controle mudou. Atualize o aparelho antes de enviar entrada.','stale_session':True}
        if self.target is None or not self.owner_check(self.target[2]) or not self.control:
            return {'ok':False,'reason':'Vídeo e controle direto ainda não conectados.'}
        try:
            action=payload.get('action')
            if action=='touch':
                phase={'down':0,'up':1,'move':2,'cancel':3}.get(payload.get('phase'))
                x,y=float(payload['x']),float(payload['y'])
                if phase is None or not all(math.isfinite(v) and 0<=v<=1 for v in [x,y]): raise ValueError()
                w,h=self.width,self.height
                if not w or not h: raise ValueError()
                message=struct.pack('>BBQiiHHHII',2,phase,0,min(w-1,int(x*w)),min(h-1,int(y*h)),w,h,0 if phase in [1,3] else 65535,0,0)
            elif action in {'home','back','key'}:
                key={'home':3,'back':4}.get(action) if action!='key' else {'Backspace':67,'Enter':66,'Tab':61,'ArrowUp':19,'ArrowDown':20,'ArrowLeft':21,'ArrowRight':22}.get(payload.get('key'))
                if key is None: raise ValueError()
                message=struct.pack('>BBiii',0,0,key,0,0)+struct.pack('>BBiii',0,1,key,0,0)
            elif action=='text':
                value=payload.get('text','')
                if not isinstance(value,str) or not value or len(value)>256 or any(ord(c)<32 for c in value): raise ValueError()
                data=value.encode();message=struct.pack('>BI',1,len(data))+data
            else: raise ValueError()
            with self.input_lock: self.control.sendall(message)
            return {'ok':True,'transport':'scrcpy-control'}
        except (ValueError,TypeError,KeyError,OSError,struct.error):
            return {'ok':False,'reason':'Entrada inválida ou canal de controle desconectado.'}

    def _produce(self,target):
        adb,serial,lab=target
        base=(adb,'-s',serial)
        process=video=control=None
        remote='/data/local/tmp/huntmob-video-'+VERSION+'.jar'
        try:
          with stream_slot():
            attempt_started=time.monotonic()
            with self.condition:
                if self.connection_attempts:self.reconnect_count+=1
                self.connection_attempts+=1;self.first_frame_ms=None;self.last_frame_at=0
            if _run(base+('emu','avd','name'),timeout=5).stdout.splitlines()[0]!=lab: raise ValueError('AVD não corresponde ao laboratório.')
            path=server_path()
            if _run(base+('push',str(path),remote),timeout=15).returncode: raise OSError('Video push failed')
            scid=0x48554e54
            if _run(base+('forward',f'tcp:{self.forward_port}',f'localabstract:scrcpy_{scid:08x}'),timeout=5).returncode: raise OSError('Video forward failed')
            process=subprocess.Popen(base+('shell',f'CLASSPATH={remote}','app_process','/','com.genymobile.scrcpy.Server',VERSION,f'scid={scid:08x}','tunnel_forward=true','audio=false','control=true','clipboard_autosync=false','send_device_meta=false','send_dummy_byte=false','max_size=1440','max_fps=60','video_bit_rate=8000000','video_codec=h264','video_codec_options=i-frame-interval=1','power_on=false','cleanup=true'),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            deadline=time.monotonic()+8
            while True:
                try:
                    video=socket.create_connection(('127.0.0.1',self.forward_port),timeout=1)
                    control=socket.create_connection(('127.0.0.1',self.forward_port),timeout=1)
                    video.settimeout(1)
                    codec=read_exact(video,4)
                    if codec!=b'h264': raise OSError('Unsupported codec')
                    break
                except OSError:
                    if video: video.close()
                    if control: control.close()
                    if process.poll() is not None or time.monotonic()>deadline: raise OSError('H264 server did not connect')
                    time.sleep(.1)
            video.settimeout(3);control.settimeout(2)
            with self.condition: self.control=control;self.started=time.monotonic();self.frames=0
            # Device messages are deliberately discarded: clipboard forwarding is disabled.
            def drain():
                try:
                    while not self.closing.is_set():
                        if not control.recv(65536): break
                except OSError: pass
            threading.Thread(target=drain,daemon=True).start()
            while not self.closing.is_set() and time.monotonic()-self.last_viewer<10:
                if time.monotonic()-self.started>MAX_STREAM_SECONDS: raise TimeoutError('Video session duration exceeded')
                if not select.select([video],[],[],1)[0]:
                    last=self.last_frame_at or self.started
                    if time.monotonic()-last>STREAM_STALL_SECONDS:
                        with self.condition:self.stall_count+=1
                        raise TimeoutError('Video stream stalled')
                    continue
                header=read_exact(video,12);flags,size=struct.unpack('>QI',header)
                if flags & SESSION:
                    width,height=struct.unpack('>II',header[4:])
                    if not 0<width<=8192 or not 0<height<=8192: raise ValueError('Invalid video geometry')
                    with self.condition:
                        self.width=width;self.height=height;self.prefix=[header];self.packets=[];self.queue_bytes=len(header);self.config_sequence=self.sequence+1
                    continue
                if size>4*1024*1024: raise ValueError('Video packet too large')
                packet=header+read_exact(video,size)
                with self.condition:
                    if flags & CONFIG:
                        self.prefix=self.prefix[:1]+[packet];self.packets=[];self.queue_bytes=sum(len(item) for item in self.prefix);self.config_sequence=self.sequence+1
                    else:
                        if flags & KEY:self.packets=[];self.queue_bytes=sum(len(item) for item in self.prefix)
                        self.sequence+=1;self.frames+=1;self.packets.append((self.sequence,packet));self.queue_bytes+=len(packet)
                        now=time.monotonic();self.last_frame_at=now
                        if self.first_frame_ms is None:self.first_frame_ms=round((now-attempt_started)*1000,1)
                        if len(self.packets)>240 or self.queue_bytes>MAX_CODEC_QUEUE_BYTES:raise ValueError('Video GOP exceeded bounded queue')
                    self.condition.notify_all()
        except (OSError,ValueError,IndexError,RuntimeError,subprocess.TimeoutExpired) as error:
            with self.condition: self.error=str(error);self.condition.notify_all()
        finally:
            with self.condition: self.control=None
            for connection in [video,control]:
                if connection: connection.close()
            if process:
                process.terminate()
                try: process.wait(2)
                except subprocess.TimeoutExpired: process.kill();process.wait(2)
            _run(base+('forward','--remove',f'tcp:{self.forward_port}'),timeout=5)
            with self.condition:
                if not self.error: self.error='Video session closed'
                self.condition.notify_all()

CODEC_RELAY=CodecRelay()
