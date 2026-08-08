const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('helper', {
  state: () => ipcRenderer.invoke('helper:state'),
  save: (setup) => ipcRenderer.invoke('helper:save', setup),
  start: () => ipcRenderer.invoke('helper:start'),
  stop: () => ipcRenderer.invoke('helper:stop'),
  reset: () => ipcRenderer.invoke('helper:reset'),
  notices: () => ipcRenderer.invoke('helper:notices'),
  open: (key) => ipcRenderer.invoke('helper:open', key),
  onState: (cb) => ipcRenderer.on('helper-state', (_event, value) => cb(value)),
  onLog: (cb) => ipcRenderer.on('helper-log', (_event, value) => cb(value)),
});
