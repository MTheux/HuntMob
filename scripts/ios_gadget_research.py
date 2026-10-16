"""Experimental own-fixture Gadget probe. Not a validated product provider."""
import hashlib,json,lzma,plistlib,re,shutil,subprocess,time,urllib.request
from pathlib import Path
from huntmob import ios_worker
from huntmob.dynamic_runtime import private_json

VERSION='17.23.3'
ASSET_SHA256='62680b4f37243cc85d868a49466028e392795f4ffeeccb1003cf238f48fd9656'
URL=f'https://github.com/frida/frida/releases/download/{VERSION}/frida-gadget-{VERSION}-ios-simulator-universal.dylib.xz'
BUNDLE='com.huntmob.ios.gadget.lab'
CONFIG={'interaction':{'type':'script','path':'HuntMobObserver.js'},'runtime':'qjs','code_signing':'required'}
OBSERVER="""// AUTHORIZED HUNTMOB FIXTURE ONLY. Metadata; no hooks, keys, buffers or network.
rpc.exports = { init() {
  const home = new NativeFunction(Module.getGlobalExportByName('getenv'), 'pointer', ['pointer'])(Memory.allocUtf8String('HOME')).readUtf8String();
  if (!home || !home.includes('/data/Containers/Data/Application/')) throw new Error('Fixture container unavailable');
  const output = new File(home + '/Documents/huntmob-frida-probe.json', 'w');
  output.write(JSON.stringify({kind:'native-metadata',arch:Process.arch,pid:Process.id,module_count:Process.enumerateModules().length,at_ms:Date.now()}));
  output.flush(); output.close();
} };
"""
LOADER='#include <dlfcn.h>\n__attribute__((constructor)) static void huntmob_probe(void) { dlopen("@executable_path/Frameworks/FridaGadget.dylib", RTLD_NOW|RTLD_LOCAL); }\n'

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def root():return ios_worker.folder()/'gadget-fixture'

def build():
    ios_worker.owned()  # No download/build for an absent or unowned lab.
    project=Path(__file__).resolve().parents[1]
    source=project/'components/ios-lab/LabApp.swift'
    if not source.is_file():raise ValueError('Fonte da fixture HuntMob não está incluída neste worker.')
    folder=root();folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    library=folder/'FridaGadget.source.dylib'
    provenance=folder/'source.json'
    if library.is_file() and provenance.is_file():
        recorded=json.loads(provenance.read_text())
        if recorded.get('asset_sha256')!=ASSET_SHA256 or recorded.get('library_sha256')!=digest(library):raise ValueError('Cache Gadget com hash divergente.')
    else:
        with urllib.request.urlopen(URL,timeout=45) as response:data=response.read(32*1024*1024+1)
        if len(data)>32*1024*1024 or hashlib.sha256(data).hexdigest()!=ASSET_SHA256:raise ValueError('Gadget oficial não passou na verificação de hash.')
        content=lzma.decompress(data)
        if len(content)>64*1024*1024:raise ValueError('Gadget excede limite de tamanho.')
        library.write_bytes(content);library.chmod(0o600)
        private_json(provenance,{'version':VERSION,'source':URL,'asset_sha256':ASSET_SHA256,'library_sha256':digest(library)})
    app=folder/'HuntMobGadget.app';framework=app/'Frameworks';framework.mkdir(parents=True,exist_ok=True)
    gadget=framework/'FridaGadget.dylib';shutil.copyfile(library,gadget)
    (framework/'FridaGadget.config').write_text(json.dumps(CONFIG))
    (framework/'HuntMobObserver.js').write_text(OBSERVER)
    loader=folder/'loader.c';loader.write_text(LOADER)
    sdk=subprocess.check_output(['xcrun','--sdk','iphonesimulator','--show-sdk-path'],text=True,timeout=10).strip()
    subprocess.run(['xcrun','--sdk','iphonesimulator','clang','-target','arm64-apple-ios17.0-simulator','-isysroot',sdk,'-c',str(loader),'-o',str(folder/'loader.o')],check=True,capture_output=True,timeout=30)
    subprocess.run(['xcrun','--sdk','iphonesimulator','swiftc','-target','arm64-apple-ios17.0-simulator','-sdk',sdk,'-parse-as-library','-O',str(source),str(folder/'loader.o'),'-o',str(app/'HuntMobLab')],check=True,capture_output=True,timeout=120)
    (app/'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':BUNDLE,'CFBundleName':'HuntMobGadget','CFBundleDisplayName':'HuntMob Gadget','CFBundleExecutable':'HuntMobLab','CFBundlePackageType':'APPL','CFBundleShortVersionString':'1.0','CFBundleVersion':'1','MinimumOSVersion':'17.0','UIDeviceFamily':[1,2],'UILaunchScreen':{},'NSFaceIDUsageDescription':'Fixture autorizada de teste biométrico.','NSAppTransportSecurity':{'NSAllowsLocalNetworking':True}}))
    for target in [gadget,app]:
        subprocess.run(['codesign','--force','--sign','-',str(target)],check=True,capture_output=True,timeout=30)
    private_json(folder/'build.json',{'version':VERSION,'bundle_id':BUNDLE,'binary_sha256':digest(app/'HuntMobLab'),'gadget_sha256':digest(gadget),'observer_sha256':hashlib.sha256(OBSERVER.encode()).hexdigest()})
    return app

def prepare():
    with ios_worker.IOS_LOCK:
        if ios_worker.owned().get('package_id') not in {None,'',BUNDLE}:
            raise ValueError('Crie um lab iOS separado e vazio; o app atual será preservado.')
        app=build()
        result=ios_worker.install_app(app)
        return {**result,'reason':'Fixture HuntMob com Gadget instalada. Use a sonda de metadados; não há listener, hooks ou jailbreak.'}

def inspect():
    with ios_worker.IOS_LOCK:
        record=ios_worker.owned()
        if record.get('package_id')!=BUNDLE:raise ValueError('Selecione a fixture HuntMob com Gadget neste lab.')
        app_path=ios_worker.sim('get_app_container',record['udid'],BUNDLE,'app',timeout=8)
        data_path=ios_worker.sim('get_app_container',record['udid'],BUNDLE,'data',timeout=8)
        if app_path.returncode or data_path.returncode:raise ValueError('Fixture Gadget não está instalada no lab.')
        app=Path(app_path.stdout.strip());framework=app/'Frameworks'
        receipt=json.loads((root()/'build.json').read_text())
        if record.get('binary_sha256')!=receipt.get('binary_sha256') or digest(app/'HuntMobLab')!=receipt.get('binary_sha256') or digest(framework/'FridaGadget.dylib')!=receipt.get('gadget_sha256') or digest(framework/'HuntMobObserver.js')!=hashlib.sha256(OBSERVER.encode()).hexdigest() or json.loads((framework/'FridaGadget.config').read_text())!=CONFIG:
            raise ValueError('Fixture ou sonda mudou; prepare novamente o build autorizado.')
        started=int(time.time()*1000)
        launched=ios_worker.sim('launch','--terminate-running-process',record['udid'],BUNDLE,timeout=30)
        pid=re.search(r': (\d+)\s*$',launched.stdout)
        if launched.returncode or not pid:raise ValueError('Fixture Gadget não abriu.')
        output=Path(data_path.stdout.strip())/'Documents/huntmob-frida-probe.json'
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            try:event=json.loads(output.read_text())
            except (OSError,ValueError):event={}
            if event.get('at_ms',0)>=started and event.get('pid')==int(pid[1]):break
            time.sleep(.1)
        else:raise ValueError('Gadget não retornou a sonda. Nenhum sucesso foi presumido.')
        if event.get('kind')!='native-metadata' or event.get('arch')!='arm64' or type(event.get('module_count')) is not int or not 0<event['module_count']<=10000:
            raise ValueError('Retorno da sonda inválido.')
        report={'provider':'frida-gadget-script','runtime':'apple-simulator','package_id':BUNDLE,'binary_sha256':record['binary_sha256'],'frida_version':VERSION,'jailbreak':False,'network_listener':False,'finding_created':False,'scope':'fixed-read-only-probe','events':[{'kind':event['kind'],'arch':event['arch'],'module_count':event['module_count']}]}
        private_json(ios_worker.folder()/'gadget-probe.json',report)
        return {'ok':True,'receipt':report}

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Sonda experimental de metadados; runtime ainda não validado.')
    parser.add_argument('--authorized-fixture',action='store_true')
    parser.add_argument('--build',action='store_true')
    args=parser.parse_args()
    if not args.authorized_fixture:
        print(json.dumps({'ready':False,'validated':False,'reason':'Pesquisa experimental. Execução exige --authorized-fixture e um lab separado da aplicação do cliente.'}))
        raise SystemExit(2)
    try:
        if args.build:prepare()
        print(json.dumps(inspect(),ensure_ascii=False,indent=2))
    except (OSError,ValueError,subprocess.SubprocessError):
        print(json.dumps({'ready':False,'validated':False,'reason':'Gadget não retornou uma sonda validada. O teste não habilita Frida, jailbreak ou IPA físico.'}))
        raise SystemExit(2)
