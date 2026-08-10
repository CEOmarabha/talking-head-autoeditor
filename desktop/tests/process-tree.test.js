const assert = require('assert');
const { EventEmitter } = require('events');
const { stopProcessTree } = require('../lib/process-tree');

(async () => {
  const calls = [];
  const fakeSpawn = (command, args, options) => {
    calls.push({ command, args, options });
    const child = new EventEmitter();
    process.nextTick(() => child.emit('close', 0));
    return child;
  };
  await stopProcessTree({ pid: 4321 }, 'win32', fakeSpawn);
  assert.deepStrictEqual(calls, [{
    command: 'taskkill.exe',
    args: ['/pid', '4321', '/T', '/F'],
    options: { windowsHide: true },
  }]);

  let signal = null;
  await stopProcessTree({ pid: 55, kill: (value) => { signal = value; } },
    'darwin', fakeSpawn);
  assert.strictEqual(signal, 'SIGTERM');

  const originalKill = process.kill;
  const groupSignals = [];
  process.kill = (pid, value) => { groupSignals.push({ pid, value }); };
  try {
    await stopProcessTree({
      pid: 77, __autoeditorProcessGroup: true,
      kill: () => { throw new Error('group process must not use child.kill'); },
    }, 'darwin', fakeSpawn);
  } finally {
    process.kill = originalKill;
  }
  assert.deepStrictEqual(groupSignals, [{ pid: -77, value: 'SIGTERM' }]);
})();
