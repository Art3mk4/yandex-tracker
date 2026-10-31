import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [vue()],
  server: {
    // локальная разработка: API уже крутится в docker (порт из .env)
    proxy: { '/api': 'http://127.0.0.1:8787' },
  },
})
