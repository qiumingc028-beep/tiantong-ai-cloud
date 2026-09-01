import {contextBridge,ipcRenderer} from 'electron';
contextBridge.exposeInMainWorld('jdAgent',{apiBase:process.env.TIANTONG_API_BASE||'https://internal.tiantongai.com',capture:(id:number,name:string,subject:string)=>ipcRenderer.invoke('capture-store',id,name,subject)});
