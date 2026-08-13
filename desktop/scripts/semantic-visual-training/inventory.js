'use strict';

const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {
  INVENTORY_SCHEMA,
  TRAINING_HARDWARE_FLOOR,
} = require('./contract');

function powershell(script) {
  const result = spawnSync('powershell.exe', [
    '-NoProfile', '-NonInteractive', '-Command', script,
  ], { encoding: 'utf8', windowsHide: true, timeout: 30_000 });
  if (result.status !== 0) {
    throw new Error(result.stderr || result.stdout || 'hardware inventory failed');
  }
  return String(result.stdout || '').trim();
}

function parseJson(text, label) {
  try {
    return JSON.parse(text);
  } catch (_) {
    throw new Error(`${label} was not JSON`);
  }
}

function integer(value) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.max(0, Math.floor(number)) : 0;
}

function collectWindowsInventory() {
  const raw = powershell(`
    $cs = Get-CimInstance Win32_ComputerSystem
    $os = Get-CimInstance Win32_OperatingSystem
    $cpu = Get-CimInstance Win32_Processor
    $gpu = @(Get-CimInstance Win32_VideoController)
    $disk = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'"
    [ordered]@{
      cpu = $cpu.Name
      cores = $cpu.NumberOfCores
      logical_processors = $cpu.NumberOfLogicalProcessors
      ram_bytes = [int64]$cs.TotalPhysicalMemory
      free_ram_bytes = [int64]$os.FreePhysicalMemory * 1024
      gpus = @($gpu | ForEach-Object {
        [ordered]@{
          name = $_.Name
          adapter_ram_bytes = [int64]($_.AdapterRAM)
          driver = $_.DriverVersion
          pnp = $_.PNPDeviceID
        }
      })
      disk_bytes = [int64]$disk.Size
      disk_free_bytes = [int64]$disk.FreeSpace
      os = "$($os.Caption) $($os.Version)"
    } | ConvertTo-Json -Compress -Depth 5
  `);
  return parseJson(raw, 'Windows hardware inventory');
}

function webgpuSupport() {
  const electronCandidates = [
    path.resolve(__dirname, '..', '..', 'node_modules', 'electron', 'dist', 'electron.exe'),
    path.resolve(__dirname, '..', '..', '..', '.local-tools', 'desktop-npm',
      'node_modules', 'electron', 'dist', 'electron.exe'),
  ];
  const electron = electronCandidates.find((file) => fs.existsSync(file)) || '';
  return {
    electron_present: !!electron,
    electron_path_bound: !!electron,
    wasm_simd_runtime_present: fs.existsSync(path.resolve(
      __dirname, '..', '..', 'helper', 'vision',
      'ort-wasm-simd-threaded.wasm')),
    note: 'WebGPU/WASM qualification still requires three offline Electron runs of the production evaluator',
  };
}

function assess(inventory) {
  const dedicatedNvidia = (inventory.gpus || []).some((gpu) =>
    /nvidia/i.test(gpu.name || '') && integer(gpu.adapter_ram_bytes) >=
      TRAINING_HARDWARE_FLOOR.minDedicatedVramBytes);
  const ramOk = integer(inventory.ram_bytes) >= TRAINING_HARDWARE_FLOOR.minRamBytes;
  const diskOk = integer(inventory.disk_free_bytes) >=
    TRAINING_HARDWARE_FLOOR.minFreeDiskBytes;
  const reasons = [];
  if (!ramOk) reasons.push('system RAM below 32 GiB training floor');
  if (!dedicatedNvidia) {
    reasons.push('no dedicated GPU with at least 16 GiB VRAM');
  }
  if (!diskOk) reasons.push('free disk below 80 GiB training floor');
  return {
    can_parameter_efficient_train: ramOk && dedicatedNvidia && diskOk,
    can_full_finetune: false,
    blocking_reasons: reasons,
  };
}

function collectInventory() {
  const hardware = process.platform === 'win32'
    ? collectWindowsInventory()
    : {
      cpu: os.cpus()[0]?.model || 'unknown',
      cores: os.cpus().length,
      logical_processors: os.cpus().length,
      ram_bytes: os.totalmem(),
      free_ram_bytes: os.freemem(),
      gpus: [],
      disk_bytes: 0,
      disk_free_bytes: 0,
      os: `${os.type()} ${os.release()}`,
    };
  const assessment = assess(hardware);
  return {
    schema_version: INVENTORY_SCHEMA,
    collected_at: new Date().toISOString(),
    platform: process.platform,
    arch: process.arch,
    hardware,
    runtimes: webgpuSupport(),
    assessment,
  };
}

function main() {
  const inventory = collectInventory();
  const output = process.argv.includes('--output')
    ? path.resolve(process.argv[process.argv.indexOf('--output') + 1])
    : '';
  const text = `${JSON.stringify(inventory, null, 2)}\n`;
  if (output) {
    fs.mkdirSync(path.dirname(output), { recursive: true });
    fs.writeFileSync(output, text, { flag: 'wx' });
  }
  process.stdout.write(text);
}

if (require.main === module) {
  try { main(); }
  catch (error) {
    process.stderr.write(`${error.stack || error.message}\n`);
    process.exitCode = 1;
  }
}

module.exports = { collectInventory, assess };
