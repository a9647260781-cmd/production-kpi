import { expect, test, type Page } from "@playwright/test";

const runtimeEnv = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process?.env ?? {};
const apiTarget = runtimeEnv.KPD_E2E_API_TARGET ?? "http://127.0.0.1:8010";

const roleLandings: Record<string, string> = {
  assembly1: "/scan",
  assembly2: "/scan",
  assembly3: "/scan",
  solder: "/scan",
  qc: "/quality",
  foreman: "/foreman",
  auditor: "/quality",
  planner: "/workforce",
  supervisor: "/",
  admin: "/",
};

async function loginAs(page: Page, username: string) {
  await page.goto("/login");
  if (["planner", "admin"].includes(username)) await page.getByRole("button", { name: "Показать планировщика и администратора" }).click();
  await page.getByRole("button", { name: new RegExp(username, "i") }).click();
  await page.getByRole("button", { name: "Открыть рабочее место" }).click();
  await expect.poll(() => new URL(page.url()).pathname).toBe(roleLandings[username]);
  await expect(page.locator(".demo-marker:visible").first()).toBeVisible();
}

async function openNavigation(page: Page, name: string) {
  const menu = page.getByRole("button", { name: "Открыть меню" });
  if (await menu.isVisible()) await menu.click();
  const link = page.getByRole("navigation", { name: "Основная навигация" }).getByRole("link", { name, exact: true });
  if (await link.count()) await link.click();
}

async function logout(page: Page) {
  await page.getByRole("button", { name: "Выйти" }).click();
  await expect(page).toHaveURL(/\/login$/);
}

test("начальник смены видит живую сводку и отчёт", async ({ page }, testInfo) => {
  await loginAs(page, "supervisor");
  await expect(page.getByRole("heading", { name: "Сводка смены" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Пять рядов" })).toBeVisible();
  await expect(page.locator(".production-row")).toHaveCount(5);
  const gateFailed = await page.getByText("Проверка качества не пройдена").isVisible();
  if (gateFailed) {
    await expect(page.getByText("Оценка завершена")).toBeVisible();
    await expect(page.getByText("Расчётный · не утверждён")).toBeVisible();
    await expect(page.getByRole("button", { name: /^КПД/ })).not.toContainText("Нет данных");
  }
  await page.screenshot({ path: testInfo.outputPath("dashboard.png"), fullPage: true });
  await page.screenshot({ path: testInfo.project.name === "mobile" ? "../docs/assets/mvp-dashboard-mobile.png" : "../docs/assets/mvp-dashboard.png", fullPage: true });

  await openNavigation(page, "Отчёты");
  await expect(page.getByRole("heading", { name: "Отчёты и утверждение" })).toBeVisible();
  await expect(page.getByText("Раздельные контуры")).toBeVisible();

  await openNavigation(page, "Журнал аудита");
  await expect(page.getByRole("heading", { name: "Журнал аудита" })).toBeVisible();
});

test("ролевое меню, landing и прямые URL соответствуют рабочим задачам", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "Полная матрица ролей проверяется один раз на desktop");
  const cases = [
    { username: "assembly1", links: [], forbidden: "/configuration", forbiddenApi: "/api/v1/route-versions" },
    { username: "solder", links: [], forbidden: "/entities?qr=DEMO-WIP-001", forbiddenApi: "/api/v1/entities" },
    { username: "qc", links: [], forbidden: "/scan", forbiddenApi: "/api/v1/work-sessions" },
    { username: "foreman", links: [], forbidden: "/configuration", forbiddenApi: "/api/v1/route-versions" },
    { username: "planner", links: ["Состав и часы", "Нормы и план", "Отчёты"], forbidden: "/scan", forbiddenApi: "/api/v1/work-sessions" },
    { username: "auditor", links: ["Изделия и маршрут", "ОТК и переделки", "Отчёты", "Журнал аудита"], forbidden: "/workforce", forbiddenApi: "/api/v1/assignments" },
    { username: "supervisor", links: ["Сводка", "Изделия и маршрут", "Отчёты", "Журнал аудита"], forbidden: "/scan", forbiddenApi: "/api/v1/work-sessions" },
  ];

  for (const roleCase of cases) {
    await loginAs(page, roleCase.username);
    const nav = page.getByRole("navigation", { name: "Основная навигация" });
    if (roleCase.links.length) await expect(nav.getByRole("link")).toHaveText(roleCase.links);
    else await expect(nav).toHaveCount(0);
    if (roleCase.username === "auditor") {
      await expect(page.getByRole("tab", { name: "Независимый аудит" })).toHaveAttribute("aria-selected", "true");
      await expect(page.getByLabel("Исходное решение")).toBeVisible();
      await expect(page.getByLabel("Решение", { exact: true })).toHaveCount(0);
    }
    if (roleCase.username === "assembly1") {
      await page.screenshot({ path: testInfo.outputPath("assembly-workstation.png"), fullPage: true });
      await page.screenshot({ path: "../docs/assets/mvp-assembly.png", fullPage: true });
    }

    const forbiddenRequests: string[] = [];
    const observe = (request: { url(): string }) => {
      if (request.url().includes(roleCase.forbiddenApi)) forbiddenRequests.push(request.url());
    };
    page.on("request", observe);
    await page.goto(roleCase.forbidden);
    await expect(page.getByRole("heading", { name: "Раздел не входит в задачи этой роли" })).toBeVisible();
    await page.waitForTimeout(150);
    expect(forbiddenRequests, `${roleCase.username}: закрытая страница не должна вызывать ${roleCase.forbiddenApi}`).toHaveLength(0);
    page.off("request", observe);
    if (["assembly1", "solder", "qc", "foreman"].includes(roleCase.username)) {
      await page.goto("/");
      await expect.poll(() => new URL(page.url()).pathname).toBe(roleLandings[roleCase.username]);
    }
    await logout(page);
  }

  await loginAs(page, "admin");
  const adminNav = page.getByRole("navigation", { name: "Основная навигация" });
  await expect(adminNav.getByRole("link")).toHaveText(["Сводка", "Сканирование", "Изделия и маршрут", "Маршруты и новые QR", "Состав и часы", "ОТК и переделки", "Нормы и план", "Отчёты", "Журнал аудита"]);
  await page.goto("/configuration");
  await expect(page.getByRole("heading", { name: "Маршруты и новые QR" })).toBeVisible();
});

test("оператор открывает QR-лист из backend seed", async ({ page }, testInfo) => {
  await loginAs(page, "assembly1");
  await expect(page.getByRole("heading", { name: "Сканирование QR" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Демо QR-коды" })).toHaveCount(0);
  await expect(page.locator(".sample-codes")).toHaveCount(0);
  const scanInput = page.getByLabel(/QR детали/);
  await expect(scanInput).toBeEnabled();
  await scanInput.fill("DEMO-UNKNOWN-QR");
  await page.getByRole("button", { name: "Подтвердить" }).click();
  await expect(page.getByText(/Исправьте QR или рабочий контекст/)).toBeVisible();
  await expect(scanInput).toBeEnabled();
  await expect.poll(() => page.evaluate(() => localStorage.getItem("kpd-demo.pending-scan.v1"))).toBeNull();
  await logout(page);

  await loginAs(page, "admin");
  await openNavigation(page, "Сканирование");
  await page.getByRole("link", { name: "Демо QR-коды" }).click();
  await expect(page.getByRole("heading", { name: "Демо QR-коды" })).toBeVisible();
  await expect(page.locator(".qr-label")).toHaveCount(4);
  await expect(page.locator(".qr-canvas svg").first()).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("qr-sheet.png"), fullPage: true });
});

test("бригадир видит только свой ряд, его состав и серверные итоги", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "Scoped foreman workspace проверяется один раз на desktop");
  await loginAs(page, "foreman");
  await expect(page.getByRole("heading", { name: "Рабочее место бригадира" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Основная навигация" })).toHaveCount(0);
  for (const title of ["Состав ряда", "Выполнено за смену", "Проблемные сканы", "Переделки ряда"]) {
    await expect(page.getByRole("heading", { name: title })).toBeVisible();
  }

  const response = await page.request.get("/api/v1/me/foreman-shift-summary?limit=10");
  expect(response.ok()).toBe(true);
  const summary = await response.json() as {
    row: { id: string; code: string; name: string };
    roster: Array<{ employee: { display_name: string } | null }>;
    primary_completed: number;
    rework_completed: number;
    problems: Array<{ id: string }>;
    reworks: Array<{ id: string }>;
  };
  const meResponse = await page.request.get("/api/v1/auth/me");
  const me = await meResponse.json() as { user: { roles: Array<{ name: string; row_id: string | null }> } };
  const foremanRole = me.user.roles.find((role) => role.name === "FOREMAN");
  expect(foremanRole?.row_id).toBeTruthy();
  expect(summary.row.id).toBe(foremanRole?.row_id);
  await expect(page.getByText(summary.row.name, { exact: true })).toBeVisible();
  await expect(page.getByTestId("foreman-primary-count")).toHaveText(String(summary.primary_completed));
  await expect(page.getByTestId("foreman-rework-count")).toHaveText(String(summary.rework_completed));
  await expect(page.locator(".foreman-roster-list li")).toHaveCount(summary.roster.length);
  for (const item of summary.roster.filter((entry) => entry.employee)) await expect(page.locator(".foreman-roster-list").getByText(item.employee!.display_name, { exact: true })).toBeVisible();
  await expect(page.locator("[data-problem-id]")).toHaveCount(summary.problems.length);
  await expect(page.locator("[data-rework-id]")).toHaveCount(summary.reworks.length);
  await expect(page.getByText("Сборка 2", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Сборка 3", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Пайка", { exact: true })).toHaveCount(0);
  await expect(page.getByText("ОТК", { exact: true })).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath("foreman-workspace.png"), fullPage: true });
  await page.screenshot({ path: "../docs/assets/mvp-foreman.png", fullPage: true });
});

test("мобильное рабочее место бригадира сохраняет четыре блока", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile", "Проверка предназначена для viewport 390 px");
  await loginAs(page, "foreman");
  await expect(page.getByRole("navigation", { name: "Основная навигация" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Открыть меню" })).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
  await expect(page.getByRole("heading", { name: "Состав ряда" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Выполнено за смену" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Проблемные сканы" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Переделки ряда" })).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: testInfo.outputPath("foreman-mobile.png") });
  await page.screenshot({ path: "../docs/assets/mvp-foreman-mobile.png" });
});

test("личный счётчик и последние сканы сохраняются после reload и не растут от дубля", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "Мутационный worker-сценарий выполняется один раз");
  const qr = `DEMO-WORKER-${Date.now()}`;

  await loginAs(page, "admin");
  await openNavigation(page, "Маршруты и новые QR");
  await page.getByLabel("QR-код").fill(qr);
  await page.getByRole("button", { name: "Создать объект" }).click();
  await expect(page.getByText(new RegExp(`QR ${qr} зарегистрирован`))).toBeVisible();
  await logout(page);

  await loginAs(page, "solder");
  const primaryCount = page.getByTestId("worker-primary-count");
  await expect(primaryCount).toHaveText(/^\d+$/);
  const before = Number(await primaryCount.textContent());
  const input = page.getByLabel(/QR детали/);
  await input.fill(qr);
  await input.press("Enter");
  await expect(page.locator('.worker-current-result[data-status="ACCEPTED"]')).toBeVisible();
  await expect(primaryCount).toHaveText(String(before + 1));
  await expect(page.locator(".worker-history-list li").filter({ hasText: qr })).toHaveCount(1);
  expect(await page.locator(".worker-history-list li").count()).toBeLessThanOrEqual(10);

  await page.reload();
  await expect(primaryCount).toHaveText(String(before + 1));
  await expect(page.locator(".worker-history-list li").filter({ hasText: qr })).toHaveCount(1);

  await input.fill(qr);
  await input.press("Enter");
  await expect(page.locator(".worker-current-result")).toContainText("Уже учтено");
  await expect(primaryCount).toHaveText(String(before + 1));
  await expect(page.locator(".worker-history-list li").filter({ hasText: qr })).toHaveCount(1);
});

test("мобильная навигация не обрезает русский интерфейс", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile", "Проверка предназначена для viewport 390 px");
  await loginAs(page, "supervisor");
  await expect(page.locator("body")).not.toHaveCSS("overflow-x", "scroll");
  await page.getByRole("button", { name: "Открыть меню" }).click();
  await expect(page.getByRole("navigation", { name: "Основная навигация" })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("mobile-menu.png"), fullPage: true });
});

test("мобильное рабочее место сборщика оставляет только сканирование", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile", "Проверка предназначена для viewport 390 px");
  await loginAs(page, "assembly2");
  await expect(page.getByRole("heading", { name: "Сканирование QR" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Основная навигация" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Открыть меню" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Демо QR-коды" })).toHaveCount(0);
  await page.evaluate(() => window.scrollTo(0, 0));
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
  await page.screenshot({ path: testInfo.outputPath("assembly-mobile-menu.png") });
  await page.screenshot({ path: "../docs/assets/mvp-assembly-mobile.png" });
  await expect(page.getByLabel(/QR детали/)).toBeVisible();
});

test("мобильное рабочее место ОТК оставляет только проверку", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile", "Проверка предназначена для viewport 390 px");
  await loginAs(page, "qc");
  await expect(page.getByRole("heading", { name: "Контроль ОТК" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Основная навигация" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Открыть меню" })).toHaveCount(0);
  await expect(page.getByLabel("QR узла или изделия")).toBeVisible();
  await expect(page.getByRole("button", { name: "Годен", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Брак", exact: true })).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: testInfo.outputPath("qc-mobile.png") });
  await page.screenshot({ path: "../docs/assets/mvp-qc-mobile.png" });
});

test("ОТК атомарно фиксирует брак, открывает переделку и проводит повторный контроль", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "Последовательный мутационный сценарий выполняется один раз");
  const qr = `DEMO-REWORK-${Date.now()}`;

  await loginAs(page, "admin");
  await openNavigation(page, "Маршруты и новые QR");
  await page.getByLabel("QR-код").fill(qr);
  await page.getByRole("button", { name: "Создать объект" }).click();
  await expect(page.getByText(new RegExp(`QR ${qr} зарегистрирован`))).toBeVisible();
  await logout(page);

  async function scanAs(username: string, rework: boolean) {
    await loginAs(page, username);
    const primaryBefore = Number(await page.getByTestId("worker-primary-count").textContent());
    const reworkBefore = Number(await page.getByTestId("worker-rework-count").textContent());
    const input = page.getByLabel(/QR детали/);
    await input.fill(qr);
    if (rework) {
      await input.press("Tab");
      await expect(page.getByRole("radio", { name: /Переделка/ })).toBeChecked();
    }
    await page.getByRole("button", { name: "Подтвердить" }).click();
    await expect(page.locator('.worker-current-result[data-status="ACCEPTED"]')).toBeVisible();
    const counts = {
      primaryBefore,
      reworkBefore,
      primaryAfter: Number(await page.getByTestId("worker-primary-count").textContent()),
      reworkAfter: Number(await page.getByTestId("worker-rework-count").textContent()),
    };
    await logout(page);
    return counts;
  }

  await scanAs("solder", false);
  const assemblyAfterPrimary = await scanAs("assembly2", false);
  expect(assemblyAfterPrimary.primaryAfter).toBe(assemblyAfterPrimary.primaryBefore + 1);
  expect(assemblyAfterPrimary.reworkAfter).toBe(assemblyAfterPrimary.reworkBefore);

  await loginAs(page, "qc");
  await page.screenshot({ path: testInfo.outputPath("qc-workspace.png"), fullPage: true });
  await page.screenshot({ path: "../docs/assets/mvp-qc.png", fullPage: true });
  const checked = page.getByTestId("qc-checked-count");
  const checkedBefore = Number(await checked.textContent());
  await page.getByLabel("QR узла или изделия").fill(qr);
  await page.getByRole("button", { name: "Брак", exact: true }).click();
  await page.getByLabel("Причина брака").selectOption("DEMO-ASSEMBLY");
  await page.getByRole("button", { name: "Подтвердить брак" }).click();
  await expect(page.locator('.qc-current-result[data-status="ACCEPTED"]')).toContainText("Брак");
  await expect(checked).toHaveText(String(checkedBefore + 1));
  await expect(page.locator(".qc-history-list li").filter({ hasText: qr })).toHaveCount(1);
  await page.reload();
  await expect(checked).toHaveText(String(checkedBefore + 1));
  await page.getByText("Открыть переделку").click();
  await expect(page.getByLabel("Проверка с браком")).toContainText(qr);
  await page.getByLabel("Повторная операция").selectOption({ label: "Сборка" });
  await page.getByLabel("Причина переделки").fill("E2E: повторная сборка после решения ОТК");
  await page.getByRole("button", { name: "Открыть", exact: true }).click();
  await expect(page.getByText(/Переделка открыта отдельно/)).toBeVisible();
  await logout(page);

  const assemblyAfterRework = await scanAs("assembly2", true);
  expect(assemblyAfterRework.primaryAfter).toBe(assemblyAfterPrimary.primaryAfter);
  expect(assemblyAfterRework.reworkAfter).toBe(assemblyAfterPrimary.reworkAfter + 1);

  await loginAs(page, "qc");
  const checkedBeforeReinspection = Number(await page.getByTestId("qc-checked-count").textContent());
  const reinspectionsBefore = Number(await page.getByTestId("qc-reinspection-count").textContent());
  await page.getByLabel("QR узла или изделия").fill(qr);
  await page.getByRole("button", { name: "Годен", exact: true }).click();
  await expect(page.locator('.qc-current-result[data-status="ACCEPTED"]')).toContainText("Годен · повторно");
  await expect(page.getByTestId("qc-checked-count")).toHaveText(String(checkedBeforeReinspection + 1));
  await expect(page.getByTestId("qc-reinspection-count")).toHaveText(String(reinspectionsBefore + 1));
  await expect(page.locator(".qc-history-list li").filter({ hasText: qr })).toHaveCount(2);
});

test("ОТК очищает только matching terminal reject и сохраняет личный итог", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "Мутационный QC-сценарий выполняется один раз");
  await loginAs(page, "qc");
  const checked = page.getByTestId("qc-checked-count");
  const before = Number(await checked.textContent());
  const input = page.getByLabel("QR узла или изделия");
  await input.fill(`DEMO-UNKNOWN-QC-${Date.now()}`);
  await page.getByRole("button", { name: "Годен", exact: true }).click();
  await expect(page.getByText(/Исправьте QR или рабочий контекст/)).toBeVisible();
  await expect(input).toBeEnabled();
  await expect(checked).toHaveText(String(before));
  await expect.poll(() => page.evaluate(() => localStorage.getItem("kpd-demo.pending-qc-inspection.v1"))).toBeNull();
});

test("один pending блокирует worker и ОТК в обе стороны", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "Проверка общего local pending выполняется один раз");
  await loginAs(page, "qc");
  await page.evaluate(() => {
    const eventId = crypto.randomUUID();
    localStorage.setItem("kpd-demo.pending-scan.v1", JSON.stringify({
      eventId, actorId: "other-worker", actorName: "Другой работник",
      body: { event_id: eventId, work_session_id: "unknown", subject_qr: "DEMO-PENDING-WORKER", event_type: "COMPLETE", attempt_type: "PRIMARY" },
      createdAt: new Date().toISOString(),
    }));
  });
  await page.reload();
  await expect(page.getByText("Операция ожидает подтверждения")).toBeVisible();
  await expect(page.getByLabel("QR узла или изделия")).toBeDisabled();
  await page.evaluate(() => localStorage.removeItem("kpd-demo.pending-scan.v1"));
  await page.reload();
  await page.evaluate(() => localStorage.setItem("kpd-demo.pending-qc-inspection.v1", JSON.stringify({
    inspectionId: "pending-qc-cross-role", actorId: "other-qc", actorName: "Другой контролёр", createdAt: new Date().toISOString(),
    body: { inspection_id: "pending-qc-cross-role", work_session_id: "unknown", subject_qr: "DEMO-PENDING-QC", decision: "ACCEPT", defect_code: null },
  })));
  await logout(page);
  await loginAs(page, "assembly1");
  await expect(page.getByText("Проверка ОТК ожидает подтверждения")).toBeVisible();
  await expect(page.getByLabel(/QR детали/)).toBeDisabled();
  await page.evaluate(() => localStorage.removeItem("kpd-demo.pending-qc-inspection.v1"));
});

test("потерянный ответ ОТК восстанавливается тем же UUID без второго решения", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "Последовательный мутационный QC-сценарий выполняется один раз");
  const qr = `DEMO-QC-LOST-${Date.now()}`;

  await loginAs(page, "admin");
  await openNavigation(page, "Маршруты и новые QR");
  await page.getByLabel("QR-код").fill(qr);
  await page.getByRole("button", { name: "Создать объект" }).click();
  await expect(page.getByText(new RegExp(`QR ${qr} зарегистрирован`))).toBeVisible();
  await logout(page);

  for (const username of ["solder", "assembly3"]) {
    await loginAs(page, username);
    const input = page.getByLabel(/QR детали/);
    await input.fill(qr);
    await input.press("Enter");
    await expect(page.locator('.worker-current-result[data-status="ACCEPTED"]')).toBeVisible();
    await logout(page);
  }

  await loginAs(page, "qc");
  const count = page.getByTestId("qc-checked-count");
  const before = Number(await count.textContent());
  let serverStatus = 0;
  let statusLookupsBeforeReload = 0;
  await page.route("**/api/v1/qc-inspections/*/status", async (route) => {
    statusLookupsBeforeReload += 1;
    await route.abort("failed");
  });
  await page.route("**/api/v1/qc-inspections", async (route) => {
    const request = route.request();
    const requestHeaders = request.headers();
    const response = await fetch(`${apiTarget}/api/v1/qc-inspections`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "cookie": requestHeaders.cookie ?? "",
        "x-csrf-token": requestHeaders["x-csrf-token"] ?? "",
      },
      body: request.postData(),
    });
    serverStatus = response.status;
    await response.text();
    await route.abort("failed");
  }, { times: 1 });

  await page.getByLabel("QR узла или изделия").fill(qr);
  await page.getByRole("button", { name: "Годен", exact: true }).click();
  await expect(page.getByText("Проверка ещё не подтверждена")).toBeVisible();
  await expect.poll(() => serverStatus).toBe(200);
  expect(statusLookupsBeforeReload).toBe(0);
  const inspectionId = await page.evaluate(() => JSON.parse(localStorage.getItem("kpd-demo.pending-qc-inspection.v1") ?? "null")?.inspectionId as string);
  expect(inspectionId).toBeTruthy();

  await page.unroute("**/api/v1/qc-inspections");
  await page.unroute("**/api/v1/qc-inspections/*/status");
  await page.reload();
  await expect.poll(() => page.evaluate(() => localStorage.getItem("kpd-demo.pending-qc-inspection.v1"))).toBeNull();
  await expect(count).toHaveText(String(before + 1));
  await expect(page.locator(".qc-history-list li").filter({ hasText: qr })).toHaveCount(1);
  const decisionsResponse = await page.request.get("/api/v1/quality/decisions");
  expect(decisionsResponse.ok()).toBe(true);
  const decisions = await decisionsResponse.json() as { items: Array<{ request_id: string }> };
  expect(decisions.items.filter((item) => item.request_id === inspectionId)).toHaveLength(1);
});

test("потерянный ответ восстанавливается тем же UUID без второго факта", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "Последовательный мутационный сценарий выполняется один раз");
  const qr = `DEMO-E2E-${Date.now()}`;

  await loginAs(page, "admin");
  await openNavigation(page, "Маршруты и новые QR");
  await page.getByLabel("QR-код").fill(qr);
  await page.getByRole("button", { name: "Создать объект" }).click();
  await expect(page.getByText(new RegExp(`QR ${qr} зарегистрирован`))).toBeVisible();
  await logout(page);

  await loginAs(page, "solder");
  await openNavigation(page, "Сканирование");
  let serverResponse: { status: number; body: unknown } | null = null;
  let statusLookupsBeforeReload = 0;
  await page.route("**/api/v1/operation-events/*/status", async (route) => {
    statusLookupsBeforeReload += 1;
    await route.abort("failed");
  });
  await page.route("**/api/v1/operation-events", async (route) => {
    const request = route.request();
    const requestHeaders = request.headers();
    const response = await fetch(`${apiTarget}/api/v1/operation-events`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "cookie": requestHeaders.cookie ?? "",
        "x-csrf-token": requestHeaders["x-csrf-token"] ?? "",
      },
      body: request.postData(),
    });
    serverResponse = { status: response.status, body: await response.json() };
    await route.abort("failed");
  }, { times: 1 });
  const input = page.getByLabel(/QR детали/);
  await input.fill(qr);
  await page.getByRole("button", { name: "Подтвердить" }).click();
  await expect(page.getByText("Операция ещё не подтверждена")).toBeVisible();
  await expect.poll(() => serverResponse).toMatchObject({ status: 200 });
  expect(statusLookupsBeforeReload).toBe(0);
  const eventId = await page.evaluate(() => JSON.parse(localStorage.getItem("kpd-demo.pending-scan.v1") ?? "null")?.eventId as string);
  expect(eventId).toBeTruthy();

  await page.unroute("**/api/v1/operation-events");
  await page.unroute("**/api/v1/operation-events/*/status");
  await page.reload();
  await expect(page.locator('.worker-current-result[data-status="ACCEPTED"]')).toBeVisible();
  await expect.poll(() => page.evaluate(() => localStorage.getItem("kpd-demo.pending-scan.v1"))).toBeNull();

  const entityResponse = await page.request.get(`/api/v1/entities/by-qr/${encodeURIComponent(qr)}`);
  expect(entityResponse.ok()).toBe(true);
  const entity = await entityResponse.json() as { id: string };
  const timelineResponse = await page.request.get(`/api/v1/entities/${entity.id}/timeline`);
  const timeline = await timelineResponse.json() as { items: Array<{ id: string; kind: string }> };
  expect(timeline.items.filter((item) => item.kind === "route" && item.id === eventId)).toHaveLength(1);
});
