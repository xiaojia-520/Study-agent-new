import { fileURLToPath, URL } from 'node:url'
import fs from 'node:fs'
import path from 'node:path'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'
import tailwindcss from '@tailwindcss/vite'

const httpsKeyPath = path.resolve('./certs/192.168.1.63+2-key.pem')
const httpsCertPath = path.resolve('./certs/192.168.1.63+2.pem')
const hasHttpsCert = fs.existsSync(httpsKeyPath) && fs.existsSync(httpsCertPath)

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    vue(),
    vueDevTools(),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    },
  },
  server: {
    host: '0.0.0.0',
    ...(hasHttpsCert
      ? {
          https: {
            key: fs.readFileSync(httpsKeyPath),
            cert: fs.readFileSync(httpsCertPath),
          },
        }
      : {}),
  },
})
