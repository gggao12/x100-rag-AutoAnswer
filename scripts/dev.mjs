import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const python = process.env.PYTHON || 'python';
const apiPort = process.env.X100_API_PORT || '8005';
const env = { ...process.env, X100_DEV_MODE: '1', X100_PROJECT_ROOT: root, X100_API_PORT: apiPort };
const api = spawn(python, ['-m', 'server.api'], { cwd: root, env, stdio: 'inherit' });
let vite;
let stopped = false;
let apiReady = false;

function stop(code = 0) {
  if (stopped) return;
  stopped = true;
  api.kill();
  vite?.kill();
  process.exitCode = code;
}

api.on('error', () => {
  console.error('无法启动 Python RAG API。请检查 Python、PyTorch 和 Transformers。');
  stop(1);
});
api.on('exit', (code) => {
  if (!stopped) {
    console.error('Python RAG API exited before the development server was ready.');
    stop(code || 1);
  }
});
process.on('SIGINT', () => stop(0));
process.on('SIGTERM', () => stop(0));

// Python 健康检查通过后才启动 Vite，避免出现前端可打开但 API 未就绪的半启动状态。
const startedAt = Date.now();
while (Date.now() - startedAt < 30_000) {
  try {
    const response = await fetch(`http://127.0.0.1:${apiPort}/api/health`);
    if (response.ok) { apiReady = true; break; }
  } catch {}
  if (stopped) break;
  await new Promise((resolve) => setTimeout(resolve, 250));
}

if (stopped || !apiReady) {
  if (!stopped) console.error('RAG API readiness check timed out.');
  stop(1);
  process.exit(1);
}

vite = spawn(process.execPath, [path.join(root, 'node_modules', 'vite', 'bin', 'vite.js'), '--host', '127.0.0.1'], {
  cwd: root, env, stdio: 'inherit',
});
vite.on('error', () => stop(1));
vite.on('exit', (code) => { if (!stopped) stop(code || 0); });

