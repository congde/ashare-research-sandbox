/**
 * Centralized auth token storage using sessionStorage (per-tab isolation).
 *
 * sessionStorage is scoped to each browser tab, so multiple tabs can hold
 * different user sessions simultaneously. On first access, any legacy
 * localStorage tokens are migrated automatically.
 */

const KEYS = {
  token: "de_token",
  refresh: "de_refresh_token",
  role: "de_active_role",
} as const;

/** One-time migration from localStorage → sessionStorage */
function migrate(): void {
  for (const key of Object.values(KEYS)) {
    const v = localStorage.getItem(key);
    if (v) {
      sessionStorage.setItem(key, v);
      localStorage.removeItem(key);
    }
  }
}

// Run migration on module load
migrate();

export const authStorage = {
  getToken(): string | null {
    return sessionStorage.getItem(KEYS.token);
  },
  setToken(v: string): void {
    sessionStorage.setItem(KEYS.token, v);
  },

  getRefresh(): string | null {
    return sessionStorage.getItem(KEYS.refresh);
  },
  setRefresh(v: string): void {
    sessionStorage.setItem(KEYS.refresh, v);
  },

  // Holds the WIRE role string (employer / operator) to stay consistent with
  // the JWT active_role; UserContext maps it to/from RoleKey for the UI.
  getRole(): "employer" | "operator" | null {
    return sessionStorage.getItem(KEYS.role) as "employer" | "operator" | null;
  },
  setRole(v: string): void {
    sessionStorage.setItem(KEYS.role, v);
  },

  clear(): void {
    sessionStorage.removeItem(KEYS.token);
    sessionStorage.removeItem(KEYS.refresh);
    sessionStorage.removeItem(KEYS.role);
  },

  isLoggedIn(): boolean {
    return !!sessionStorage.getItem(KEYS.token);
  },
};
