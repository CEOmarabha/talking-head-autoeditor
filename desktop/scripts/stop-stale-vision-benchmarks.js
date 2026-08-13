'use strict';

const {
  stopStaleVisionBenchmarkTrees,
} = require('../lib/stale-vision-benchmark-processes');

(async () => {
  const stopped = await stopStaleVisionBenchmarkTrees({
    protectPids: [process.pid, process.ppid].filter(Boolean),
  });
  const receipt = {
    schema_version: 'autoeditor-stale-vision-benchmark-cleanup/v1',
    stopped_count: stopped.length,
    stopped: stopped.map((item) => ({
      pid: item.pid,
      ppid: item.ppid,
      name: item.name,
    })),
  };
  process.stdout.write(`${JSON.stringify(receipt)}\n`);
})().catch((error) => {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
});
