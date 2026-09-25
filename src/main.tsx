import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './styles.css';
import './auth.css';

// 单页应用入口：把 RAG 界面挂载到 index.html 的 #root，并加载相关样式。
createRoot(document.getElementById('root')!).render(
  <React.StrictMode><App /></React.StrictMode>,
);
