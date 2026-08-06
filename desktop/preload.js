const { contextBridge, ipcRenderer, webUtils } = require('electron');

contextBridge.exposeInMainWorld('api', {
  state: () => ipcRenderer.invoke('state'),
  saveKey: (key) => ipcRenderer.invoke('save-key', key),
  pickFiles: (kind) => ipcRenderer.invoke('pick-files', kind),
  filePath: (file) => webUtils.getPathForFile(file),
  pickOutdir: () => ipcRenderer.invoke('pick-outdir'),
  transcribe: (job) => ipcRenderer.invoke('transcribe', job),
  edit: (job) => ipcRenderer.invoke('edit', job),
  cancel: () => ipcRenderer.invoke('cancel'),
  reveal: (p) => ipcRenderer.invoke('reveal', p),
  openPath: (p) => ipcRenderer.invoke('open-path', p),
  onLog: (cb) => ipcRenderer.on('engine-log', (_e, line) => cb(line)),
});
