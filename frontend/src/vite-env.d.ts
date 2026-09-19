/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Backend origin, e.g. https://nazar-api.onrender.com. Empty ('') when the
   * backend serves this build itself (same-origin). */
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
