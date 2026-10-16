const {app,BrowserWindow,ipcMain,dialog,Menu}=require('electron'),path=require('node:path'),{pathToFileURL}=require('node:url'),{workerUrl,protocolUrl}=require('./policy.cjs');
let setup,viewer;const setupUrl=pathToFileURL(path.join(__dirname,'setup.html')).href;
app.enableSandbox();
function protect(win,origin){
 win.webContents.setWindowOpenHandler(()=>({action:'deny'}));
 for(const name of ['will-navigate','will-redirect'])win.webContents.on(name,(event,target)=>{try{if(origin==='null'?target!==setupUrl:new URL(target).origin!==origin)event.preventDefault();}catch{event.preventDefault();}});
 win.webContents.session.setPermissionRequestHandler((_contents,_permission,callback)=>callback(false));win.webContents.session.setPermissionCheckHandler(()=>false);
}
function connect(value){
 const url=workerUrl(value);const previous=viewer;
 viewer=new BrowserWindow({width:560,height:920,minWidth:400,minHeight:600,title:'HuntMob Viewer',backgroundColor:'#101012',webPreferences:{nodeIntegration:false,contextIsolation:true,sandbox:true,webSecurity:true,allowRunningInsecureContent:false,partition:'huntmob-viewer'}});
 if(previous&&!previous.isDestroyed())previous.close();
 protect(viewer,new URL(url).origin);
 viewer.webContents.on('did-fail-load',(_event,code,_description,_url,isMain)=>{if(isMain&&code!==-3)dialog.showMessageBox(viewer,{type:'error',message:'Worker não respondeu',detail:'Verifique URL, Tailscale e computador ligado. Certificados continuam sendo validados.'});});
 viewer.loadURL(url);if(setup&&!setup.isDestroyed())setup.close();
}
function showSetup(){setup=new BrowserWindow({width:600,height:430,resizable:false,title:'HuntMob Viewer',backgroundColor:'#101012',webPreferences:{preload:path.join(__dirname,'preload.cjs'),nodeIntegration:false,contextIsolation:true,sandbox:true}});protect(setup,'null');setup.loadFile(path.join(__dirname,'setup.html'));}
if(!app.requestSingleInstanceLock())app.quit();
app.on('open-url',(event,value)=>{event.preventDefault();app.whenReady().then(()=>{try{connect(protocolUrl(value));}catch{showSetup();}});});
app.on('second-instance',(_event,args)=>{const value=args.find(v=>v.startsWith('huntmob-viewer:'));try{if(value)connect(protocolUrl(value));else if(viewer)viewer.focus();}catch{showSetup();}});
app.whenReady().then(()=>{
 app.setAsDefaultProtocolClient('huntmob-viewer');
 ipcMain.handle('connect-worker',(event,value)=>{if(event.senderFrame?.url!==setupUrl)throw Error('Origem inválida');try{connect(value);return {ok:true};}catch(error){return {ok:false,reason:error.message};}});
 Menu.setApplicationMenu(Menu.buildFromTemplate([{label:'HuntMob',submenu:[{label:'Conectar a outro worker',click:showSetup},{role:'quit'}]},{label:'Janela',submenu:[{role:'reload'},{role:'togglefullscreen'},{role:'minimize'}]}]));
 const protocol=process.argv.find(v=>v.startsWith('huntmob-viewer:'));if(protocol){try{connect(protocolUrl(protocol));}catch{showSetup();}}else showSetup();
});
app.on('window-all-closed',()=>app.quit());
