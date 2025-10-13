import { contextBridge, ipcRenderer } from 'electron';

contextBridge.exposeInMainWorld('sa', {
  getHWID: () => ipcRenderer.invoke('get-hwid'),
  verifyKey: (key) => ipcRenderer.invoke('verify-key', key),
  getHWInfo: () => ipcRenderer.invoke('get-hwinfo')
});
