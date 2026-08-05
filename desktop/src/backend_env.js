'use strict';

const fs = require('node:fs');
const fsp = require('node:fs/promises');

async function swapBackendEnv(venvDir, stagingDir, logLine = () => {}) {
  const backupDir = `${venvDir}.previous`;
  let previousMoved = false;

  try {
    if (fs.existsSync(venvDir)) {
      await fsp.rm(backupDir, { recursive: true, force: true });
      await fsp.rename(venvDir, backupDir);
      previousMoved = true;
    }
    await fsp.rename(stagingDir, venvDir);
  } catch (error) {
    if (previousMoved && !fs.existsSync(venvDir) && fs.existsSync(backupDir)) {
      try { await fsp.rename(backupDir, venvDir); } catch { /* preserve original error */ }
    }
    throw error;
  }

  if (previousMoved) {
    try {
      await fsp.rm(backupDir, { recursive: true, force: true });
    } catch (error) {
      logLine(`旧后端环境清理失败（新环境已生效）：${error.message}`);
    }
  }
}

async function recoverBackendEnvBackup(venvDir, logLine = () => {}) {
  const backupDir = `${venvDir}.previous`;
  if (!fs.existsSync(venvDir) && fs.existsSync(backupDir)) {
    logLine('recovering backend environment interrupted during directory swap ...');
    await fsp.rename(backupDir, venvDir);
  }
}

module.exports = { recoverBackendEnvBackup, swapBackendEnv };
