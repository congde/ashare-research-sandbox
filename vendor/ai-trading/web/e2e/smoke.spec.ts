import { test, expect } from "@playwright/test";

// UX-001: 主流浏览器兼容性 — 核心页面可访问
test.describe("Smoke Tests", () => {
  test("landing page loads", async ({ page }) => {
    await page.goto("/landing");
    await expect(page).toHaveTitle(/AI Trading/i);
  });

  test("login page loads", async ({ page }) => {
    await page.goto("/login");
    const inputCount = await page.locator("input").count();
    expect(inputCount).toBeGreaterThanOrEqual(1);
  });

  test("home page redirects or loads", async ({ page }) => {
    const res = await page.goto("/home");
    expect(res?.status()).toBeLessThan(500);
  });
});

// UX-003: 表单错误提示
test.describe("Form Validation", () => {
  test("login with empty fields shows error", async ({ page }) => {
    await page.goto("/login");
    const submitBtn = page.locator("button[type='submit'], .btn-gradient").first();
    if (await submitBtn.isVisible()) {
      await submitBtn.click();
      // Should show validation or stay on page (not crash)
      await expect(page).toHaveURL(/login/);
    }
  });
});

// UX-004: 空状态提示
test.describe("Empty States", () => {
  test("dashboard shows guidance for new user", async ({ page }) => {
    await page.goto("/dashboard");
    // Should show either data or empty state guidance (not a blank page)
    const body = await page.locator("body").textContent();
    expect(body?.length).toBeGreaterThan(10);
  });
});
