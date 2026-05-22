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
const backendIpv6Host = '240a:4283:802:aa7:9e80:afdb:e24b:d94'
const backendHttpTarget = `http://[${backendIpv6Host}]:8000`
const backendWsTarget = `ws://[${backendIpv6Host}]:8000`

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
    host: '127.0.0.1',
    proxy: {
      '/sessions': {
        target: backendHttpTarget,
        changeOrigin: true,
      },
      '/lessons': {
        target: backendHttpTarget,
        changeOrigin: true,
      },
      '/ws': {
        target: backendWsTarget,
        changeOrigin: true,
        ws: true,
      },
    },
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
