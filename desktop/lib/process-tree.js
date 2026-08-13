const { spawn } = require('child_process');

function stopProcessTree(proc, platform = process.platform,
  spawnImpl = spawn) {
  if (!proc || !proc.pid) return Promise.resolve();
  if (platform !== 'win32') {
    try {
      if (proc.__autoeditorProcessGroup) process.kill(-proc.pid, 'SIGTERM');
      else proc.kill('SIGTERM');
    } catch (_) { /* already exited */ }
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    const killer = spawnImpl('taskkill.exe', [
      '/pid', String(proc.pid), '/T', '/F',
    ], { windowsHide: true });
    killer.on('error', () => resolve());
    killer.on('close', () => resolve());
  });
}

module.exports = { stopProcessTree };
