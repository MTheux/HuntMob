#!/usr/bin/env python3
"""Build an owned arm64/iPhoneOS fixture; ad-hoc signing is lab-only."""
import hashlib
import json
import plistlib
import subprocess
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
component = root/'components/ios-device-lab'
app = component/'HuntMobDeviceLab.app'
app.mkdir(exist_ok=True)
binary = app/'HuntMobDeviceLab'
sdk = subprocess.check_output(['xcrun','--sdk','iphoneos','--show-sdk-path'],text=True).strip()
subprocess.run(['xcrun','--sdk','iphoneos','clang','-target','arm64-apple-ios14.0',
                '-isysroot',sdk,'-fobjc-arc','-framework','UIKit','-framework','Foundation',
                str(component/'main.m'),'-o',str(binary)],check=True,timeout=60)
info = {'CFBundleIdentifier':'com.huntmob.ios.virtual.fixture','CFBundleExecutable':binary.name,
        'CFBundleName':'HuntMob Virtual Lab','CFBundlePackageType':'APPL',
        'CFBundleVersion':'1','CFBundleShortVersionString':'1.0','MinimumOSVersion':'14.0',
        'CFBundleSupportedPlatforms':['iPhoneOS'],'UIDeviceFamily':[1],
        'LSRequiresIPhoneOS':True,'UILaunchScreen':{},
        'UISupportedInterfaceOrientations':['UIInterfaceOrientationPortrait']}
(app/'Info.plist').write_bytes(plistlib.dumps(info))
subprocess.run(['codesign','--force','--sign','-',str(app)],check=True,timeout=30)
archive = component/'HuntMobDeviceLab.ipa'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as output:
    for file in app.rglob('*'):
        if file.is_file(): output.write(file,'Payload/'+str(file.relative_to(component)))
receipt={'schema':1,'bundle_id':info['CFBundleIdentifier'],'platform':'iPhoneOS',
         'minimum_ios':'14.0','binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),
         'ipa_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
         'signature':'ad-hoc, isolated emulated lab only','installed':False,'launched':False}
(component/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt))
