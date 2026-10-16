const {contextBridge,ipcRenderer}=require('electron');contextBridge.exposeInMainWorld('huntmobConnect',{connect:value=>ipcRenderer.invoke('connect-worker',value)});
