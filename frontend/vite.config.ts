import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
// Single source of truth for the local dev backend port, so Vite's proxy
// target, .claude/launch.json's nazar-api entry, and `uvicorn --port` all
// have to agree on the same number instead of drifting independently (see
// docs/DECISIONS.md, 2026-09-25 Phase 2 entry - this used to default to
// 8000 here while launch.json ran uvicorn on 8017, silently breaking every
// proxied request). Override with VITE_API_PROXY_TARGET for a non-default
// local backend port; NAZAR_DEV_API_PORT is read for convenience so the same
// env var can size both the backend's --port and this proxy target.
const API=process.env.VITE_API_PROXY_TARGET||`http://127.0.0.1:${process.env.NAZAR_DEV_API_PORT||'8000'}`;
export default defineConfig({plugins:[react()],server:{proxy:Object.fromEntries(['/auth','/personas','/works','/summary','/signals','/confirmed','/image','/investigations','/evaluation','/inefficiency','/satellite','/vendor-network','/quality','/audit','/cases','/images','/metrics'].map(p=>[p,API]))}});
