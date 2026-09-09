import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({plugins:[react()],server:{proxy:{'/personas':'http://127.0.0.1:8000','/works':'http://127.0.0.1:8000','/summary':'http://127.0.0.1:8000','/image':'http://127.0.0.1:8000','/investigations':'http://127.0.0.1:8000','/evaluation':'http://127.0.0.1:8000'}}});
