"""Build our own Simulator fixture using the installed Apple SDK, without signing."""
import plistlib,subprocess
from pathlib import Path
base=Path(__file__).resolve().parents[1]
out=base/'components/ios-lab/HuntMobLab.app';out.mkdir(exist_ok=True)
sdk=subprocess.check_output(['xcrun','--sdk','iphonesimulator','--show-sdk-path'],text=True).strip()
subprocess.run(['xcrun','--sdk','iphonesimulator','swiftc','-target','arm64-apple-ios17.0-simulator','-sdk',sdk,'-parse-as-library','-O',str(base/'components/ios-lab/LabApp.swift'),'-o',str(out/'HuntMobLab')],check=True,timeout=120)
(out/'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'com.huntmob.ios.lab','CFBundleName':'HuntMobLab','CFBundleDisplayName':'HuntMob Lab','CFBundleExecutable':'HuntMobLab','CFBundlePackageType':'APPL','CFBundleShortVersionString':'1.0','CFBundleVersion':'1','MinimumOSVersion':'17.0','UIDeviceFamily':[1,2],'UILaunchScreen':{},'NSFaceIDUsageDescription':'Teste biométrico apenas na fixture autorizada do laboratório.','NSAppTransportSecurity':{'NSAllowsLocalNetworking':True}}))
print(out)
subprocess.run(['codesign','--force','--sign','-','--identifier','com.huntmob.ios.lab','--entitlements',str(base/'components/ios-lab/entitlements.plist'),str(out)],check=True,timeout=30)
