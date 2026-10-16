"""Architecture contract shared by provisioning and the actual Android worker."""
import platform


def android_host():
    host=platform.system().lower()
    machine=platform.machine().lower()
    if host not in {'darwin','windows','linux'}:
        return {'supported':False,'reason':'Sistema do worker não suportado.'}
    if machine in {'amd64','x86_64'}:
        architecture='x86_64'
    elif host=='darwin' and machine in {'arm64','aarch64'}:
        architecture='arm64-v8a'
    else:
        return {'supported':False,'host':host,'cpu':machine,'reason':'Este host não tem um Android Emulator oficial compatível. Use um worker macOS Apple Silicon ou Windows/Linux x64.'}
    return {'supported':True,'host':host,'cpu':machine,'architecture':architecture,'accelerator':{'darwin':'hvf','windows':'whpx','linux':'kvm'}[host]}
