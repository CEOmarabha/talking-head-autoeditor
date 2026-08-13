'use strict';

// Locate leftover AutoEditor *vision benchmark* process trees only.
// The shipped Helper, generic Node, and live supervised bakeoffs are left
// alone. A tree is stale when every matching process has a dead parent or a
// parent that is not a recognized benchmark supervisor.

const { spawn } = require('child_process');
const { stopProcessTree } = require('./process-tree');

const BENCHMARK_MARKERS = Object.freeze([
  'vision-capability-electron',
  'qwen3vl-bakeoff',
  'vision-benchmark-',
  '.eval-vision-',
  'autoeditor-visual-quality-electron',
  'semantic-visual-training',
]);

const SUPERVISOR_MARKERS = Object.freeze([
  'supervisor.ps1',
  'stop-stale-vision-benchmarks',
]);

const HELPER_NAME = /autoeditor helper\.exe$/i;

function normalizeHaystack(name, commandLine) {
  return `${String(name || '')}\n${String(commandLine || '')}`.toLowerCase();
}

function matchesAny(haystack, markers) {
  return markers.some((marker) => haystack.includes(marker.toLowerCase()));
}

function isVisionBenchmarkProcess(processInfo) {
  if (!processInfo || typeof processInfo !== 'object') return false;
  const haystack = normalizeHaystack(processInfo.name, processInfo.commandLine);
  if (!matchesAny(haystack, BENCHMARK_MARKERS)) return false;
  if (HELPER_NAME.test(String(processInfo.name || '')) &&
      !matchesAny(haystack, BENCHMARK_MARKERS)) {
    return false;
  }
  return true;
}

function isBenchmarkSupervisor(processInfo) {
  if (!processInfo || typeof processInfo !== 'object') return false;
  return matchesAny(
    normalizeHaystack(processInfo.name, processInfo.commandLine),
    SUPERVISOR_MARKERS);
}

function processById(processes) {
  const map = new Map();
  for (const item of processes) {
    if (Number.isSafeInteger(item?.pid) && item.pid > 0) map.set(item.pid, item);
  }
  return map;
}

function ancestorChain(processInfo, byId, seen = new Set()) {
  const chain = [];
  let current = processInfo;
  while (current && Number.isSafeInteger(current.pid) && !seen.has(current.pid)) {
    seen.add(current.pid);
    chain.push(current);
    current = Number.isSafeInteger(current.ppid) ? byId.get(current.ppid) : null;
  }
  return chain;
}

function selectStaleVisionBenchmarkProcesses(processes) {
  if (!Array.isArray(processes)) return [];
  const byId = processById(processes);
  const matches = processes.filter(isVisionBenchmarkProcess);
  const stale = [];
  for (const item of matches) {
    const chain = ancestorChain(item, byId);
    const supervised = chain.some(isBenchmarkSupervisor);
    if (!supervised) stale.push(item);
  }
  return stale.sort((left, right) => right.pid - left.pid);
}

function parseProcessList(text) {
  const parsed = JSON.parse(String(text || '[]'));
  const rows = Array.isArray(parsed) ? parsed : parsed ? [parsed] : [];
  const processes = [];
  for (const row of rows) {
    const pid = Number(row?.ProcessId);
    const ppid = Number(row?.ParentProcessId);
    if (!Number.isSafeInteger(pid) || pid < 1) continue;
    processes.push({
      pid,
      ppid: Number.isSafeInteger(ppid) ? ppid : 0,
      name: String(row?.Name || ''),
      commandLine: String(row?.CommandLine || ''),
    });
  }
  return processes;
}

function parseWmicList(text) {
  return parseProcessList(text);
}

function listWindowsProcesses({
  spawnImpl = spawn,
  platform = process.platform,
} = {}) {
  if (platform !== 'win32') return Promise.resolve([]);
  return new Promise((resolve, reject) => {
    const child = spawnImpl('powershell.exe', [
      '-NoProfile', '-NonInteractive', '-Command',
      'Get-CimInstance Win32_Process | Select-Object Name,ProcessId,ParentProcessId,CommandLine | ConvertTo-Json -Compress -Depth 3',
    ], { windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
    let stdout = '';
    let stderr = '';
    child.stdout?.setEncoding('utf8');
    child.stderr?.setEncoding('utf8');
    child.stdout?.on('data', (chunk) => { stdout += chunk; });
    child.stderr?.on('data', (chunk) => { stderr += chunk; });
    child.once('error', reject);
    child.once('close', (code) => {
      if (code !== 0) {
        reject(new Error(stderr.trim() || 'process listing failed'));
        return;
      }
      try { resolve(parseProcessList(stdout)); }
      catch (error) { reject(error); }
    });
  });
}

async function stopStaleVisionBenchmarkTrees({
  listProcesses = listWindowsProcesses,
  stopTree = stopProcessTree,
  spawnImpl = spawn,
  platform = process.platform,
  protectPids = [],
} = {}) {
  const protectedIds = new Set(
    (Array.isArray(protectPids) ? protectPids : [])
      .filter((pid) => Number.isSafeInteger(pid) && pid > 0));
  const processes = await listProcesses({ spawnImpl, platform });
  const stale = selectStaleVisionBenchmarkProcesses(processes)
    .filter((item) => !protectedIds.has(item.pid));
  for (const item of stale) {
    await stopTree({ pid: item.pid }, platform, spawnImpl);
  }
  return stale;
}

module.exports = {
  BENCHMARK_MARKERS,
  SUPERVISOR_MARKERS,
  isVisionBenchmarkProcess,
  isBenchmarkSupervisor,
  parseWmicList,
  selectStaleVisionBenchmarkProcesses,
  listWindowsProcesses,
  stopStaleVisionBenchmarkTrees,
};
