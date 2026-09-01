'use strict';

const { contextBridge, ipcRenderer } = require('electron');

const CHANNELS = Object.freeze({
  snapshot: 'workbench:snapshot',
  pair: 'workbench:pair',
  refreshStores: 'workbench:refresh-stores',
  selectStore: 'workbench:select-store',
  humanAction: 'workbench:human-action',
  syncNow: 'workbench:sync-now',
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
  syncNow: (storeUuid = null) => ipcRenderer.invoke(CHANNELS.syncNow, storeUuid),
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
