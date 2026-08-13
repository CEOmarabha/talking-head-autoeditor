'use strict';

const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const {
  isVisionBenchmarkProcess,
  isBenchmarkSupervisor,
  parseWmicList,
  selectStaleVisionBenchmarkProcesses,
  stopStaleVisionBenchmarkTrees,
} = require('../lib/stale-vision-benchmark-processes');

assert.equal(isVisionBenchmarkProcess({
  name: 'electron.exe',
  commandLine: 'C:\\repo\\desktop\\scripts\\vision-capability-electron',
}), true);
assert.equal(isVisionBenchmarkProcess({
  name: 'electron.exe',
  commandLine: 'C:\\repo\\.local-tools\\qwen3vl-bakeoff-1ee355f\\main.js',
}), true);
assert.equal(isVisionBenchmarkProcess({
  name: 'AutoEditor Helper.exe',
  commandLine: '"C:\\Users\\me\\AutoEditor Helper.exe"',
}), false, 'the shipped Helper is not a vision benchmark');
assert.equal(isVisionBenchmarkProcess({
  name: 'node.exe',
  commandLine: 'node desktop/tests/vision-electron-harness.test.js',
}), false);
assert.equal(isBenchmarkSupervisor({
  name: 'powershell.exe',
  commandLine: 'powershell.exe -File .local-tools\\qwen3vl-bakeoff-1ee355f\\supervisor.ps1',
}), true);

const listed = parseWmicList(JSON.stringify([
  {
    Name: 'powershell.exe',
    ProcessId: 100,
    ParentProcessId: 4,
    CommandLine: 'powershell.exe -File C:\\repo\\.local-tools\\qwen3vl-bakeoff-1ee355f\\supervisor.ps1',
  },
  {
    Name: 'electron.exe',
    ProcessId: 200,
    ParentProcessId: 100,
    CommandLine: 'electron.exe C:\\repo\\.local-tools\\qwen3vl-bakeoff-1ee355f',
  },
  {
    Name: 'electron.exe',
    ProcessId: 300,
    ParentProcessId: 1,
    CommandLine: 'electron.exe C:\\repo\\desktop\\scripts\\vision-capability-electron',
  },
  {
    Name: 'AutoEditor Helper.exe',
    ProcessId: 400,
    ParentProcessId: 1,
    CommandLine: '"C:\\Users\\me\\AutoEditor-0.1.4\\AutoEditor Helper.exe"',
  },
]));
assert.equal(listed.length, 4);
const stale = selectStaleVisionBenchmarkProcesses(listed);
assert.deepEqual(stale.map((item) => item.pid), [300],
  'only the orphaned vision-capability-electron tree is stale');

(async () => {
  const killed = [];
  const fakeSpawn = (command, args, options) => {
    killed.push({ command, args, options });
    const child = new EventEmitter();
    process.nextTick(() => child.emit('close', 0));
    return child;
  };
  const stopped = await stopStaleVisionBenchmarkTrees({
    platform: 'win32',
    spawnImpl: fakeSpawn,
    listProcesses: async () => listed,
    protectPids: [300],
  });
  assert.deepEqual(stopped, []);
  assert.deepEqual(killed, []);

  const stoppedNow = await stopStaleVisionBenchmarkTrees({
    platform: 'win32',
    spawnImpl: fakeSpawn,
    listProcesses: async () => listed,
  });
  assert.deepEqual(stoppedNow.map((item) => item.pid), [300]);
  assert.deepEqual(killed, [{
    command: 'taskkill.exe',
    args: ['/pid', '300', '/T', '/F'],
    options: { windowsHide: true },
  }]);
  console.log('stale vision-benchmark process selection passed');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
