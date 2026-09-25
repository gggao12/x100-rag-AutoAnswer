import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({
  plugins: [react()],
  // 只有 VITE_* 变量允许进入浏览器构建产物；DEEPSEEK_* 仅由 Python 服务端读取。
  envPrefix: 'VITE_',
  // 开发时保持浏览器同源调用，并将 /api 转发到本机 Python 服务。
  server: { proxy: { '/api': 'http://127.0.0.1:8005' } },
});





