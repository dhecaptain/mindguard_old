import axios from 'axios'
import { getToken, clearToken } from '../lib/tokenStorage'

const baseURL =
  import.meta.env.VITE_API_BASE_URL ||
  (import.meta.env.DEV ? 'http://127.0.0.1:8000/api' : '/api')

const api = axios.create({
  baseURL,
})

api.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

let _reloading401 = false
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      clearToken()
      const onAuthRoute =
        window.location.pathname.startsWith('/auth/') ||
        window.location.pathname.startsWith('/consent/') ||
        window.location.pathname === '/demo' ||
        window.location.pathname.startsWith('/demo/respond')
      if (!onAuthRoute && !_reloading401) {
        _reloading401 = true
        window.location.href = '/'
        window.setTimeout(() => {
          _reloading401 = false
        }, 2000)
      }
    }
    const msg = err.response?.data?.detail || err.message || 'Request failed'
    return Promise.reject(new Error(msg))
  }
)

export default api
