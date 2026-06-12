import { createContext, useContext, useEffect, useState, useCallback } from "react";
import type { ReactNode } from "react";
import { userApi } from "../api/services";
import type { UserProfile } from "../api/services";
import api from "../api/client";
import { authStorage } from "../utils/auth-storage";
import { type RoleKey, toRoleKey, toWireRole } from "../utils/roles";

// Frontend speaks RoleKey (trader / strategy_provider); the wire (backend,
// JWT active_role, storage) still speaks employer / operator. We map at this
// boundary (ADR-0019 §4.3). `hasRole` checks the raw wire role strings carried
// in `currentUser.roles`, so `isTrader = hasRole("employer")` etc.
interface UserContextValue {
  currentUser: UserProfile | null;
  userLoaded: boolean;
  hasRole: (role: string) => boolean;
  isAdmin: boolean;
  isTrader: boolean;
  isStrategyProvider: boolean;
  activeRole: RoleKey;
  switchRole: (role: RoleKey) => Promise<void>;
  reload: () => void;
}

const UserContext = createContext<UserContextValue>({
  currentUser: null,
  userLoaded: false,
  hasRole: () => false,
  isAdmin: false,
  isTrader: false,
  isStrategyProvider: false,
  activeRole: "trader",
  switchRole: async () => {},
  reload: () => {},
});

export function UserProvider({ children }: { children: ReactNode }) {
  const [currentUser, setCurrentUser] = useState<UserProfile | null>(null);
  const [userLoaded, setUserLoaded] = useState(false);
  const [activeRole, setActiveRole] = useState<RoleKey>(
    () => toRoleKey(authStorage.getRole())
  );

  const fetchUser = useCallback(() => {
    userApi
      .me()
      .then((r) => {
        setCurrentUser(r.data);
        // Determine the active role. We resolve in wire space (employer /
        // operator), persist the wire string, and map to RoleKey for the UI.
        const cachedRole = authStorage.getRole();
        const roles = r.data.roles ?? [];
        if (cachedRole && roles.includes(cachedRole)) {
          setActiveRole(toRoleKey(cachedRole));
        } else {
          const backendRole = (r.data as UserProfile & { active_role?: string }).active_role;
          let resolved: "employer" | "operator" = "employer";
          if (backendRole === "employer" || backendRole === "operator") {
            resolved = backendRole;
          } else {
            resolved = roles.includes("employer") ? "employer" : roles.includes("operator") ? "operator" : "employer";
          }
          setActiveRole(toRoleKey(resolved));
          authStorage.setRole(resolved);
        }
        setUserLoaded(true);
      })
      .catch(() => {
        setCurrentUser(null);
        setUserLoaded(true);
      });
  }, []);

  useEffect(() => { fetchUser(); }, [fetchUser]);

  const hasRole = (role: string) =>
    currentUser?.roles.includes("admin") || currentUser?.roles.includes(role) || false;

  const switchRole = useCallback(async (role: RoleKey) => {
    const wire = toWireRole(role);
    const res = await api.post<{ access_token: string; refresh_token: string }>(
      "/auth/switch-role",
      { active_role: wire },
    );
    authStorage.setToken(res.data.access_token);
    authStorage.setRefresh(res.data.refresh_token);
    authStorage.setRole(wire);
    setActiveRole(role);
    fetchUser();
  }, [fetchUser]);

  return (
    <UserContext.Provider value={{
      currentUser,
      userLoaded,
      hasRole,
      isAdmin: currentUser?.roles.includes("admin") ?? false,
      isTrader: hasRole("employer"),
      isStrategyProvider: hasRole("operator"),
      activeRole,
      switchRole,
      reload: fetchUser,
    }}>
      {children}
    </UserContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useCurrentUser() {
  return useContext(UserContext);
}
