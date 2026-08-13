'use strict';

const fs = require('node:fs');

const CLOSED_PIPE_CODES = new Set([
  'EPIPE',
  'EBADF',
  'EOF',
  'ERR_STREAM_DESTROYED',
]);

function writeStdoutSync(value, {
  descriptor = process.stdout?.fd,
  writeSync = fs.writeSync,
} = {}) {
  const bytes = Buffer.isBuffer(value) ? value : Buffer.from(value);
  if (!Number.isSafeInteger(descriptor) || descriptor < 0) return false;
  let offset = 0;
  try {
    while (offset < bytes.length) {
      const written = writeSync(
        descriptor, bytes, offset, bytes.length - offset, null);
      if (!Number.isSafeInteger(written) || written < 1) return false;
      offset += written;
    }
    return true;
  } catch (error) {
    if (CLOSED_PIPE_CODES.has(error?.code)) return false;
    throw error;
  }
}

module.exports = { writeStdoutSync };
