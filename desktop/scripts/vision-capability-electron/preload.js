'use strict';

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('autoeditorVisionProbe', Object.freeze({
  onRequest(callback) {
    if (typeof callback !== 'function') return;
    ipcRenderer.on('autoeditor-vision-probe-request', (_event, value) => callback(value));
  },
  result(value) {
    ipcRenderer.send('autoeditor-vision-probe-result', value);
  },
}));
