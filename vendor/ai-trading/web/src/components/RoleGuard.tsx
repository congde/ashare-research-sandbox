import { Navigate } from "react-router-dom";
import { useCurrentUser } from "../contexts/UserContext";
import type { RoleKey } from "../utils/roles";

interface RoleGuardProps {
  allow: RoleKey | "any";
  children: React.ReactNode;
}

/**
 * Route-level role guard. Redirects to dashboard if active role doesn't match.
 *
 * Usage:
 *   <RoleGuard allow="trader"><SomePage /></RoleGuard>
 */
export default function RoleGuard({ allow, children }: RoleGuardProps) {
  const { activeRole } = useCurrentUser();

  if (allow !== "any" && activeRole !== allow) {
    return <Navigate to="/dashboard" replace />;
  }

  return <>{children}</>;
}
