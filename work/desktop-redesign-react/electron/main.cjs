const { app, BrowserWindow, Menu, session } = require('electron');
const path = require('node:path');

// An isolated design preview. No production Runtime, database or configuration.
app.setName('Empire Design Preview');
app.setPath('userData', path.join(__dirname, '..', '.preview-profile-data-all'));
const ownsInstance = app.requestSingleInstanceLock();
let window;

if (!ownsInstance) app.quit();
else {
  app.on('second-instance', () => {
    if (window) {
      if (window.isMinimized()) window.restore();
      window.focus();
    }
  });
  app.whenReady().then(() => {
    Menu.setApplicationMenu(null);
    session.defaultSession.setPermissionRequestHandler((_contents, _permission, reply) => reply(false));
    window = new BrowserWindow({
      width: 1600, height: 1040, minWidth: 1000, minHeight: 720,
      title: 'Empire · 设计评审 · 全目录预览',
      backgroundColor: '#f5f5f5', autoHideMenuBar: true, show: false,
      webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true, devTools: false },
    });
    window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    window.webContents.on('will-navigate', event => event.preventDefault());
    window.loadFile(path.join(__dirname, '..', 'dist', 'index.html'));
    window.once('ready-to-show', () => window.show());
    window.on('closed', () => { window = null; });
  });
  app.on('window-all-closed', () => app.quit());
}
