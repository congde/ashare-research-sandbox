import { describe, it, expect } from "vitest";
import { toRoleKey, toWireRole, type RoleKey } from "../../utils/roles";

describe("role mapping (B-layer)", () => {
  it("maps RoleKey → wire string for /auth payloads + storage", () => {
    expect(toWireRole("trader")).toBe("employer");
    expect(toWireRole("strategy_provider")).toBe("operator");
  });

  it("maps wire string → RoleKey", () => {
    expect(toRoleKey("employer")).toBe("trader");
    expect(toRoleKey("operator")).toBe("strategy_provider");
  });

  it("falls back to trader for unknown / admin / null / undefined", () => {
    expect(toRoleKey("admin")).toBe("trader");
    expect(toRoleKey(null)).toBe("trader");
    expect(toRoleKey(undefined)).toBe("trader");
    expect(toRoleKey("garbage")).toBe("trader");
  });

  it("round-trips RoleKey through wire", () => {
    const keys: RoleKey[] = ["trader", "strategy_provider"];
    for (const k of keys) {
      expect(toRoleKey(toWireRole(k))).toBe(k);
    }
  });
});
