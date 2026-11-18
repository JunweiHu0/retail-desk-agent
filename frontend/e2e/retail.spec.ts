import { expect, test } from "@playwright/test";

test.use({ viewport: { width: 1440, height: 1000 } });

async function login(page: import("@playwright/test").Page, email = "li.ming") {
  await page.goto("/");
  await page.getByRole("button", { name: email + " ↗", exact: true }).click();
  await page.getByRole("button", { name: "登录工作台 →", exact: true }).click();
  await expect(
    page.getByRole("navigation", { name: "账户导航" }),
  ).toBeVisible();
}

test("login, profile, order approval, agent context and account isolation", async ({
  page,
}) => {
  await login(page);
  await page.getByRole("button", { name: "个人信息", exact: true }).click();
  await expect(
    page.getByText("li.ming@retail-demo.example.com", { exact: true }),
  ).toBeVisible();
  await page.screenshot({ path: "test-results/profile.png", fullPage: true });
  await page.getByRole("button", { name: "订单管理", exact: true }).click();
  const order = page.locator(".order-tile").filter({ hasText: "#W9000001" });
  await expect(order).toBeVisible();
  await page.screenshot({ path: "test-results/orders.png", fullPage: true });
  await order.getByRole("button", { name: "管理订单 →" }).click();
  await page.getByRole("button", { name: "预览取消订单", exact: true }).click();
  await page.getByRole("button", { name: "查看变更明细并处理 →" }).click();
  const approval = page.getByTestId("approval-card");
  await expect(approval).toBeVisible();
  await expect(approval.getByText("尚未执行")).toBeVisible();
  await page.getByRole("button", { name: "确认执行", exact: true }).click();
  await expect(approval).toBeHidden();
  await expect(page.getByText(/操作已完成，变更已持久化/)).toBeVisible();
  await page.getByRole("button", { name: "订单管理", exact: true }).click();
  await expect(
    page
      .locator(".order-tile")
      .filter({ hasText: "#W9000001" })
      .getByText("已取消", { exact: true }),
  ).toBeVisible();
  await page
    .locator(".order-tile")
    .filter({ hasText: "#W9000002" })
    .getByRole("button", { name: "咨询此订单" })
    .click();
  await expect(page.locator(".message.assistant").last()).toContainText(
    "#W9000002",
  );
  await page.getByRole("button", { name: "退出登录", exact: true }).click();
  await login(page, "wang.fang");
  await page.getByRole("button", { name: "订单管理", exact: true }).click();
  await expect(
    page.locator(".order-tile").filter({ hasText: "#W9000001" }),
  ).toHaveCount(0);
  await expect(
    page.locator(".order-tile").filter({ hasText: "#W9000004" }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("navigation", { name: "账户导航" }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth,
    ),
  ).toBe(false);
});

test("default address preview can be rejected without mutation", async ({
  page,
}) => {
  await login(page, "zhang.wei");
  await page.getByRole("button", { name: "个人信息", exact: true }).click();
  const field = page.getByLabel("街道地址", { exact: true });
  const before = await field.inputValue();
  await field.fill("123 Preview Only Road");
  await page.getByRole("button", { name: "预览地址变更" }).click();
  await page.getByRole("button", { name: "查看变更明细并处理 →" }).click();
  await expect(page.getByTestId("approval-card")).toBeVisible();
  await expect(page.getByTestId("approval-card")).toContainText(
    "123 Preview Only Road",
  );
  await page.getByRole("button", { name: "取消操作", exact: true }).click();
  await expect(page.getByTestId("approval-card")).toBeHidden();
  await page.getByRole("button", { name: "个人信息", exact: true }).click();
  await expect(page.getByLabel("街道地址", { exact: true })).toHaveValue(
    before,
  );
});

test("registration creates an empty private account", async ({ page }) => {
  await page.goto("/");
  await page.screenshot({ path: "test-results/login.png", fullPage: true });
  await page.getByRole("button", { name: "没有账户？注册" }).click();
  await page.getByLabel("名", { exact: true }).fill("Test");
  await page.getByLabel("姓", { exact: true }).fill("Customer");
  await page
    .getByLabel("邮箱", { exact: true })
    .fill(`web-${Date.now()}@example.com`);
  await page.getByLabel("密码", { exact: true }).fill("TestPassword123!");
  await page.getByRole("button", { name: "注册并登录", exact: true }).click();
  await page.getByRole("button", { name: "订单管理", exact: true }).click();
  await expect(page.getByText("暂无符合条件的订单。")).toBeVisible();
});
