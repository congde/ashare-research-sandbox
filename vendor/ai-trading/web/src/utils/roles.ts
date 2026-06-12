/**
 * Role terminology mapping layer — B-layer of the role-model migration
 * (employer/operator → trader/strategy_provider, see ADR-0019 §4.3).
 *
 * The **wire** protocol still speaks the legacy strings: the backend
 * `ALLOWED_ROLES`, `users.roles`, the JWT `active_role`, every `/auth/*`
 * payload, and the `de_active_role` sessionStorage value all use
 * `"employer"` / `"operator"`. Renaming those is C-layer (backend + DB
 * migration), not done yet.
 *
 * The frontend, however, speaks `RoleKey` (`"trader"` / `"strategy_provider"`)
 * everywhere user-facing. This module is the single boundary that maps between
 * the two. When C-layer lands and the wire uses the new strings directly, this
 * mapper collapses to the identity and can be deleted.
 */

/** Frontend-facing role identity. */
export type RoleKey = "trader" | "strategy_provider";

/** Legacy wire role string (backend / JWT / storage). */
export type WireRole = "employer" | "operator";

const KEY_TO_WIRE: Record<RoleKey, WireRole> = {
  trader: "employer",
  strategy_provider: "operator",
};

/** `RoleKey` → wire string, for `/auth/*` payloads and storage. */
export function toWireRole(key: RoleKey): WireRole {
  return KEY_TO_WIRE[key];
}

/**
 * Wire string (or anything) → `RoleKey`. Only `"operator"` maps to
 * `strategy_provider`; everything else (`employer`, `admin`, unknown, null)
 * falls back to `trader` — matching the historical "default to the employer
 * view" behaviour.
 */
export function toRoleKey(wire: string | null | undefined): RoleKey {
  return wire === "operator" ? "strategy_provider" : "trader";
}
