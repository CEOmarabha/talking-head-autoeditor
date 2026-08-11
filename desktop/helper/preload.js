'use strict';

const { contextBridge, ipcRenderer, webUtils } = require('electron');

function on(channel, callback) {
  if (typeof callback !== 'function') {
    throw new TypeError('Event listener must be a function');
  }
  const listener = (_event, value) => callback(value);
  ipcRenderer.on(channel, listener);
  return () => ipcRenderer.removeListener(channel, listener);
}

contextBridge.exposeInMainWorld('helper', Object.freeze({
  state: () => ipcRenderer.invoke('helper:state'),
  pickVideos: () => ipcRenderer.invoke('helper:pick-videos'),
  attachDroppedVideos: (files) => ipcRenderer.invoke(
    'helper:attach-dropped-videos',
    Array.from(files || []).map((file) => webUtils.getPathForFile(file))),
  pickOutput: () => ipcRenderer.invoke('helper:pick-output'),
  saveSettings: (settings) => ipcRenderer.invoke('helper:save-settings', settings),
  renderLocal: (request) => ipcRenderer.invoke('helper:render-local', request),
  cancelLocal: () => ipcRenderer.invoke('helper:cancel-local'),
  chatLocal: (request) => ipcRenderer.invoke('helper:chat-local', request),
  applyLocal: (request) => ipcRenderer.invoke('helper:apply-local', request),
  openResult: (resultPath) => ipcRenderer.invoke('helper:open-result', resultPath),
  openResearchSource: (url) => ipcRenderer.invoke(
    'helper:open-research-source', url),
  notices: () => ipcRenderer.invoke('helper:notices'),
  open: (key) => ipcRenderer.invoke('helper:open', key),
  onState: (callback) => on('helper-state', callback),
  onLog: (callback) => on('helper-log', callback),
  onRender: (callback) => on('helper-render', callback),
}));
