interface ImportMetaEnv {
  /** Base URL for the ANCHOR API. Defaults to `/api` (proxied by Vite in development). */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
