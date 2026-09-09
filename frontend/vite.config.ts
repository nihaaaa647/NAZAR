import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
const API='http://127.0.0.1:8000';
export default defineConfig({plugins:[react()],server:{proxy:Object.fromEntries(['/auth','/personas','/works','/summary','/signals','/confirmed','/image','/investigations','/evaluation'].map(p=>[p,API]))}});
