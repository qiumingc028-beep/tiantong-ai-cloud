'use strict';

const { contextBridge, ipcRenderer } = require('electron');

const CHANNELS = Object.freeze({
  snapshot: 'workbench:snapshot',
  pair: 'workbench:pair',
  refreshStores: 'workbench:refresh-stores',
  selectStore: 'workbench:select-store',
  setSection: 'workbench:set-section',
  recognizePage: 'workbench:recognize-page',
  syncPage: 'workbench:sync-page',
  syncAllNow: 'workbench:sync-all-now',
  humanAction: 'workbench:human-action',
  status: 'workbench:status'
});

contextBridge.exposeInMainWorld('tiantongWorkbench', Object.freeze({
  getSnapshot: () => ipcRenderer.invoke(CHANNELS.snapshot),
  pair: (pairing) => ipcRenderer.invoke(CHANNELS.pair, {
    code: pairing && pairing.code,
    deviceName: pairing && pairing.deviceName
  }),
  refreshStores: () => ipcRenderer.invoke(CHANNELS.refreshStores),
  selectStore: (storeUuid) => ipcRenderer.invoke(CHANNELS.selectStore, storeUuid),
  setSection: (section) => ipcRenderer.invoke(CHANNELS.setSection, section),
  recognizePage: () => ipcRenderer.invoke(CHANNELS.recognizePage),
  syncPage: () => ipcRenderer.invoke(CHANNELS.syncPage),
  syncAllNow: () => ipcRenderer.invoke(CHANNELS.syncAllNow),
  reportHumanAction: (storeUuid, reason) => ipcRenderer.invoke(
    CHANNELS.humanAction,
    storeUuid,
    reason
  ),
  onStatus: (listener) => {
    if (typeof listener !== 'function') return () => {};
    const handler = (_event, value) => listener(value);
    ipcRenderer.on(CHANNELS.status, handler);
    return () => ipcRenderer.removeListener(CHANNELS.status, handler);
  }
}));
