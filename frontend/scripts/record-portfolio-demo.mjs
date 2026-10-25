import { chromium, expect } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const frontendDir = resolve(scriptDir, "..");
const workspaceDir = resolve(frontendDir, "..");
const outputPath = resolve(workspaceDir, "docs", "assets", "portfolio-demo.webm");
const videoTempDir = resolve(frontendDir, "test-results", "portfolio-video");
const baseURL = process.env.KPD_DEMO_BASE_URL ?? "http://127.0.0.1:5173";
const qr = `DEMO-VIDEO-${Date.now()}`;

await mkdir(videoTempDir, { recursive: true });
await mkdir(dirname(outputPath), { recursive: true });

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  recordVideo: { dir: videoTempDir, size: { width: 1440, height: 900 } },
  reducedMotion: "reduce",
});
const page = await context.newPage();
page.setDefaultTimeout(15_000);
let recordingSucceeded = false;

const pause = (ms) => new Promise((resolvePause) => setTimeout(resolvePause, ms));

async function ensureOverlay() {
  await page.evaluate(() => {
    if (document.getElementById("portfolio-caption")) return;
    const style = document.createElement("style");
    style.textContent = `
      #portfolio-caption {
        position: fixed; left: 50%; bottom: 28px; transform: translateX(-50%);
        z-index: 2147483645; max-width: min(980px, calc(100vw - 64px));
        padding: 14px 22px; border-radius: 14px; background: rgba(4, 33, 63, .94);
        color: #fff; font: 600 22px/1.35 system-ui, sans-serif; text-align: center;
        box-shadow: 0 10px 32px rgba(6, 31, 55, .25); pointer-events: none;
        opacity: 0; transition: opacity .18s ease;
      }
      #portfolio-title {
        position: fixed; inset: 0; z-index: 2147483646; display: grid; place-items: center;
        padding: 72px; background: #f3f7fb; color: #0c2742; pointer-events: none;
        opacity: 0; transition: opacity .22s ease;
      }
      #portfolio-title > div { max-width: 1020px; text-align: center; }
      #portfolio-title h1 { margin: 0 0 22px; font: 750 52px/1.1 system-ui, sans-serif; }
      #portfolio-title p { margin: 0; font: 500 26px/1.45 system-ui, sans-serif; color: #3d5870; }
      #portfolio-cursor {
        position: fixed; z-index: 2147483647; width: 22px; height: 22px;
        border: 3px solid #0878cf; border-radius: 50%; background: rgba(255,255,255,.92);
        box-shadow: 0 2px 10px rgba(4, 33, 63, .35); pointer-events: none;
        transform: translate(-50%, -50%); transition: left .32s ease, top .32s ease;
      }
      .portfolio-focus { outline: 4px solid rgba(8,120,207,.32) !important; outline-offset: 4px !important; }
    `;
    document.head.append(style);
    const caption = document.createElement("div");
    caption.id = "portfolio-caption";
    caption.setAttribute("aria-hidden", "true");
    document.body.append(caption);
    const title = document.createElement("div");
    title.id = "portfolio-title";
    title.setAttribute("aria-hidden", "true");
    title.innerHTML = "<div><h1></h1><p></p></div>";
    document.body.append(title);
    const cursor = document.createElement("div");
    cursor.id = "portfolio-cursor";
    cursor.setAttribute("aria-hidden", "true");
    cursor.style.left = "32px";
    cursor.style.top = "32px";
    document.body.append(cursor);
  });
}

async function caption(text, ms = 4200) {
  await ensureOverlay();
  await page.evaluate((value) => {
    const node = document.getElementById("portfolio-caption");
    node.textContent = value;
    node.style.opacity = "1";
  }, text);
  await pause(ms);
}

async function titleCard(title, detail, ms = 7000) {
  await ensureOverlay();
  await page.evaluate(({ heading, copy }) => {
    const node = document.getElementById("portfolio-title");
    node.querySelector("h1").textContent = heading;
    node.querySelector("p").textContent = copy;
    node.style.opacity = "1";
  }, { heading: title, copy: detail });
  await pause(ms);
  await page.evaluate(() => { document.getElementById("portfolio-title").style.opacity = "0"; });
  await pause(500);
}

async function point(locator) {
  await locator.scrollIntoViewIfNeeded();
  await locator.evaluate((node) => node.classList.add("portfolio-focus"));
  const box = await locator.boundingBox();
  if (box) {
    await page.evaluate(({ x, y }) => {
      const cursor = document.getElementById("portfolio-cursor");
      cursor.style.left = `${x}px`;
      cursor.style.top = `${y}px`;
    }, { x: box.x + box.width / 2, y: box.y + box.height / 2 });
  }
  await pause(700);
}

async function clearPoint(locator) {
  await locator.evaluate((node) => node.classList.remove("portfolio-focus")).catch(() => {});
}

async function click(locator, text, hold = 2400) {
  if (text) await caption(text, 2600);
  await point(locator);
  await locator.click();
  await clearPoint(locator);
  await pause(hold);
}

async function typeInto(locator, value, text) {
  if (text) await caption(text, 2500);
  await point(locator);
  await locator.fill("");
  await locator.pressSequentially(value, { delay: 45 });
  await clearPoint(locator);
  await pause(1600);
}

async function loginAs(username) {
  await page.goto(`${baseURL}/login`);
  await ensureOverlay();
  if (["planner", "admin"].includes(username)) {
    await page.getByRole("button", { name: "Показать планировщика и администратора" }).click();
  }
  await page.getByRole("button", { name: new RegExp(username, "i") }).click();
  await page.getByRole("button", { name: "Открыть рабочее место" }).click();
  await page.waitForLoadState("networkidle");
  await ensureOverlay();
}

async function logout() {
  await page.getByRole("button", { name: "Выйти" }).click();
  await expect(page).toHaveURL(/\/login$/);
  await pause(1000);
}

async function openNavigation(name) {
  const menu = page.getByRole("button", { name: "Открыть меню" });
  if (await menu.isVisible().catch(() => false)) await menu.click();
  await page.getByRole("navigation", { name: "Основная навигация" })
    .getByRole("link", { name, exact: true }).click();
  await pause(2200);
}

try {
  await page.goto(`${baseURL}/login`);
  await ensureOverlay();
  await titleCard(
    "КПД производства квадрокоптеров",
    "P0-Demo · живой браузер · только синтетические данные",
    8000,
  );

  await caption("Сначала создаём уникальный DEMO-WIP через реальный административный интерфейс.", 4800);
  await loginAs("admin");
  await openNavigation("Маршруты и новые QR");
  await typeInto(page.getByLabel("QR-код"), qr, "Новый QR привязывается к опубликованной версии маршрута.");
  await click(page.getByRole("button", { name: "Создать объект" }), "Сервер проверяет уникальность QR и тип сущности.", 2500);
  await expect(page.getByText(new RegExp(`QR ${qr} зарегистрирован`))).toBeVisible();
  await caption("Объект зарегистрирован сервером. Производственный маршрут ещё не начат.", 4500);
  await logout();

  await titleCard("1 · Производство", "Пайка и сборка фиксируются отдельными QR-событиями.", 6000);
  await loginAs("solder");
  const solderInput = page.getByLabel(/QR детали/);
  await typeInto(solderInput, qr, "Работник пайки сканирует QR после завершения своей операции.");
  await caption("Enter отправляет событие; счётчик меняется только после ответа сервера.", 3000);
  await solderInput.press("Enter");
  await expect(page.locator('.worker-current-result[data-status="ACCEPTED"]')).toBeVisible();
  await caption("Пайка принята. Это операция, а не готовый квадрокоптер.", 5000);
  await logout();

  await loginAs("assembly2");
  const assemblyInput = page.getByLabel(/QR детали/);
  await typeInto(assemblyInput, qr, "На сборке видны назначенные ряд и операция — контекст не вводится вручную.");
  await assemblyInput.press("Enter");
  await expect(page.locator('.worker-current-result[data-status="ACCEPTED"]')).toBeVisible();
  await caption("Первичная сборка подтверждена. Серверный итог смены вырос ровно на одну операцию.", 5600);
  await logout();

  await titleCard("2 · ОТК", "QR → решение → причина брака сохраняются одной серверной транзакцией.", 6500);
  await loginAs("qc");
  const qcInput = page.getByLabel("QR узла или изделия");
  await typeInto(qcInput, qr, "Контролёр сканирует тот же WIP на рабочем месте ОТК.");
  await click(page.getByRole("button", { name: "Брак", exact: true }), "Выбираем «Брак»: найденный дефект — результат контроля, а не штраф ОТК.", 1800);
  const reason = page.getByLabel("Причина брака");
  await point(reason);
  await reason.selectOption("DEMO-ASSEMBLY");
  await clearPoint(reason);
  await caption("Причина взята из серверного синтетического DEMO-справочника.", 4200);
  await click(page.getByRole("button", { name: "Подтвердить брак" }), "Подтверждаем решение ОТК.", 2200);
  await expect(page.locator('.qc-current-result[data-status="ACCEPTED"]')).toContainText("Брак");
  await caption("Сервер атомарно сохранил контрольную операцию и решение «Брак».", 5000);

  await click(page.getByText("Открыть переделку"), "Переделка открывается отдельно — решение ОТК не запускает её скрыто.", 2000);
  await expect(page.getByLabel("Проверка с браком")).toContainText(qr);
  const reworkStep = page.getByLabel("Повторная операция");
  await point(reworkStep);
  await reworkStep.selectOption({ label: "Сборка" });
  await clearPoint(reworkStep);
  await typeInto(page.getByLabel("Причина переделки"), "ДЕМО: повторная сборка после решения ОТК", "Выбираем разрешённый шаг и фиксируем причину.");
  await click(page.getByRole("button", { name: "Открыть", exact: true }), "Создаём отдельный заказ переделки.", 2200);
  await expect(page.getByText(/Переделка открыта отдельно/)).toBeVisible();
  await caption("Заказ переделки открыт и связан с исходным решением ОТК.", 4600);
  await logout();

  await titleCard("3 · Переделка", "Повторная операция не увеличивает первичный выпуск.", 6000);
  await loginAs("assembly2");
  const reworkInput = page.getByLabel(/QR детали/);
  await typeInto(reworkInput, qr, "Сборщик повторно сканирует WIP.");
  await reworkInput.press("Tab");
  const reworkRadio = page.getByRole("radio", { name: /Переделка/ });
  await expect(reworkRadio).toBeChecked();
  await point(reworkRadio);
  await caption("Сервер распознал открытый заказ: режим «Переделка» выбран явно.", 5000);
  await clearPoint(reworkRadio);
  await click(page.getByRole("button", { name: "Подтвердить" }), "Подтверждаем повторную операцию.", 2200);
  await expect(page.locator('.worker-current-result[data-status="ACCEPTED"]')).toBeVisible();
  await caption("Переделка принята отдельно; первичный счётчик не получает второй кредит.", 5200);
  await logout();

  await titleCard("4 · Повторный контроль", "ОТК видит разрешённую повторную проверку после завершённой переделки.", 6200);
  await loginAs("qc");
  const reinspectionInput = page.getByLabel("QR узла или изделия");
  await typeInto(reinspectionInput, qr, "Контролёр снова сканирует WIP после переделки.");
  await click(page.getByRole("button", { name: "Годен", exact: true }), "Повторный контроль: изделие признано годным.", 2200);
  await expect(page.locator('.qc-current-result[data-status="ACCEPTED"]')).toContainText("Годен · повторно");
  await caption("Повторный контроль подтверждён. История сохраняет и брак, и переделку, и новый результат.", 5800);
  await logout();

  await titleCard("5 · Отчёт", "Расчёт приходит с backend; интерфейс не вычисляет авторитетный KPI сам.", 6200);
  await loginAs("supervisor");
  await expect(page.getByRole("heading", { name: "Сводка смены" })).toBeVisible();
  await caption("Сводка показывает пять рядов и разделяет план, объём, труд, качество и КПД.", 5200);
  await openNavigation("Отчёты");
  await expect(page.getByRole("heading", { name: "Отчёты и утверждение" })).toBeVisible();
  await caption("Отчёт различает расчётный результат, официальный результат и причины удержания.", 5600);
  await page.evaluate(() => window.scrollTo({ top: Math.min(540, document.documentElement.scrollHeight), behavior: "smooth" }));
  await pause(2600);
  await caption("Все значения здесь синтетические; нормы и пороги для реального завода ещё должны быть утверждены.", 5200);
  await logout();

  await titleCard("6 · Бригадир", "Только собственный ряд — без общей панели цеха.", 5600);
  await loginAs("foreman");
  await expect(page.getByRole("heading", { name: "Рабочее место бригадира" })).toBeVisible();
  await caption("Бригадир видит назначения своего ряда, выпуск, сохранённые ошибки и переделки.", 5200);
  await page.evaluate(() => window.scrollTo({ top: 560, behavior: "smooth" }));
  await pause(2600);
  await caption("Назначение не выдаётся за онлайн-присутствие, а чужие ряды не попадают в этот экран.", 5200);

  await titleCard(
    "Демонстрация завершена",
    `Живой P0-Demo · ${qr} · синтетические данные · не промышленное внедрение`,
    9000,
  );
  recordingSucceeded = true;
} catch (error) {
  console.error(error);
  await page.screenshot({ path: resolve(videoTempDir, "recording-failure.png"), fullPage: true }).catch(() => {});
  throw error;
} finally {
  const video = page.video();
  await page.close().catch(() => {});
  if (video) {
    const savedPath = recordingSucceeded
      ? outputPath
      : resolve(videoTempDir, `failed-${Date.now()}.webm`);
    await video.saveAs(savedPath);
  }
  await context.close().catch(() => {});
  await browser.close().catch(() => {});
}

console.log(JSON.stringify({ outputPath, qr }, null, 2));
