import axios from "axios";
import { authStorage } from "../utils/auth-storage";

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api/v1";

const api = axios.create({
  baseURL: API_BASE,
  timeout: 120_000,
  headers: { "Content-Type": "application/json" },
});

// Attach JWT token if present
api.interceptors.request.use((config) => {
  const token = authStorage.getToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// On 401, clear token and redirect to login
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err?.response?.status === 401) {
      authStorage.clear();
      if (!window.location.pathname.startsWith("/login")) {
        window.location.href = "/login";
      }
    }
    return Promise.reject(err);
  },
);

export default api;

// ── WebSocket helper ──
export function createWs(token?: string): WebSocket {
  const wsBase = import.meta.env.VITE_WS_BASE ?? "ws://localhost:8000";
  const url = token ? `${wsBase}/ws?token=${token}` : `${wsBase}/ws`;
  return new WebSocket(url);
}
