import { app, BrowserWindow, ipcMain } from 'electron';
import path from 'node:path';
import si from 'systeminformation';
import axios from 'axios';

const SERVER_URL = process.env.SERVER_URL || 'http://localhost:8080';

let mainWindow;
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 900,
    height: 600,
    backgroundColor: '#1e1e1e',
    webPreferences: {
      preload: path.join(process.cwd(), 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true
    }
  });
  mainWindow.removeMenu();
  mainWindow.loadFile(path.join(process.cwd(), 'renderer', 'index.html'));
}

app.whenReady().then(() => {
  createWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

async function computeHWID() {
  const [baseboard, cpu, disk, mem, os] = await Promise.all([
    si.baseboard(),
    si.cpu(),
    si.diskLayout(),
    si.memLayout(),
    si.osInfo()
  ]);
  const disks = (disk || []).map(d => `${d.vendor}|${d.name}|${d.serialNum}`).join(';');
  const mems = (mem || []).map(m => `${m.vendor}|${m.partNum}|${m.serialNum}`).join(';');
  const value = [
    baseboard.manufacturer,
    baseboard.model,
    baseboard.serial,
    cpu.brand,
    cpu.stepping,
    disks,
    mems,
    os.serial
  ].join('#');
  // Simple digest
  const hash = await import('node:crypto').then(({createHash}) => createHash('sha256').update(value).digest('hex'));
  return hash;
}

ipcMain.handle('get-hwid', async () => {
  return await computeHWID();
});

ipcMain.handle('get-hwinfo', async () => {
  const [system, cpu, baseboard, mem, disks, graphics, os, net] = await Promise.all([
    si.system(),
    si.cpu(),
    si.baseboard(),
    si.memLayout(),
    si.diskLayout(),
    si.graphics(),
    si.osInfo(),
    si.networkInterfaces()
  ]);
  return { system, cpu, baseboard, mem, disks, graphics, os, net };
});

ipcMain.handle('verify-key', async (_e, key) => {
  const hwid = await computeHWID();
  const res = await axios.post(`${SERVER_URL}/auth/verify`, { key, hwid });
  return res.data;
});
