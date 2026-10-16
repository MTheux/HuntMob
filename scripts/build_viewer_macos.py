#!/usr/bin/env python3
"""Build the small native macOS viewer using system WebKit (no bundled Chromium)."""
from pathlib import Path
import plistlib,subprocess
root=Path(__file__).resolve().parents[1]
app=root/'build/viewer/HuntMob Viewer-darwin-arm64/HuntMob Viewer.app'
contents=app/'Contents';(contents/'MacOS').mkdir(parents=True,exist_ok=True)
plist={'CFBundleIdentifier':'com.huntmob.viewer.lite','CFBundleName':'HuntMob Viewer','CFBundleDisplayName':'HuntMob Viewer','CFBundleExecutable':'HuntMobViewer','CFBundlePackageType':'APPL','CFBundleShortVersionString':'0.2.0','CFBundleVersion':'2','LSMinimumSystemVersion':'13.0','NSHighResolutionCapable':True,'NSAppTransportSecurity':{'NSAllowsLocalNetworking':True},'CFBundleURLTypes':[{'CFBundleURLName':'HuntMob Viewer','CFBundleURLSchemes':['huntmob-viewer']} ]}
# Separate bundle for review: packaging can select it without deleting the Electron build.
app=root/'build/viewer-native/HuntMob Viewer.app';contents=app/'Contents';(contents/'MacOS').mkdir(parents=True,exist_ok=True)
(contents/'Info.plist').write_bytes(plistlib.dumps(plist))
subprocess.run(['xcrun','swiftc','-O','-target','arm64-apple-macos13.0',str(root/'components/viewer-macos/Viewer.swift'),'-framework','AppKit','-framework','WebKit','-o',str(contents/'MacOS/HuntMobViewer')],check=True,timeout=120)
subprocess.run(['codesign','--force','--sign','-',str(app)],check=True,timeout=30)
print(app)
