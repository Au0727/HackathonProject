/**
 * ============================================================================
 * MODULE: main.tsx — Application Entry Point
 * ============================================================================
 * PURPOSE
 *   Standard React bootstrap: mounts <App /> into the #root element in
 *   index.html and loads the global stylesheet. You should not need to touch
 *   this file when integrating a backend — all integration happens in
 *   services/ (see contracts.ts and BACKEND_INTEGRATION.md).
 * ============================================================================
 */

import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './styles.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode><App /></React.StrictMode>
);
