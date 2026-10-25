# Проверки frontend demo MVP

Дата проверки: 25 октября 2026 года. Основные проверки выполнялись против живого локального API `http://127.0.0.1:8010`, без mock-ответов и без отдельного fake-data слоя во frontend. Финальная регрессия pending race повторена на изолированных `5174→8011` и fresh SQLite, не затрагивая live demo.

## Среда

- Node.js `20.19.0`, npm `10.8.2`.
- Frontend `http://127.0.0.1:5173`, Vite proxy `/api` → `http://127.0.0.1:8010`.
- Chromium, viewport desktop `1440×1000` и mobile `390×844`.
- Данные явно синтетические; E2E создаёт уникальные `DEMO-*` WIP для повторяемых мутационных сценариев.

## Выполнено

| Проверка | Результат |
|---|---|
| `npm run typecheck` | PASS |
| `npm run build` | PASS; JS 466.93 kB / 134.22 kB gzip, CSS 50.33 kB / 9.66 kB gzip |
| `npm audit --audit-level=moderate` | PASS; 0 vulnerabilities |
| `npm run test:e2e` | PASS; 16 passed, 12 intentional project/viewport skips, 0 failed |
| Isolated full E2E после pending race-fix | PASS; 16 passed, 12 intentional skips, 0 failed на `5174→8011`, fresh DB |
| Визуальная проверка снимков | PASS; desktop/mobile worker, QC, FOREMAN и dashboard |
| Portfolio video | PASS; WebM/VP9 1440×900, 249,72 с; просмотрены 7 ключевых кадров |

Живые browser-сценарии:

1. Supervisor: вход, сводка пяти рядов, authoritative KPI/row metrics, отчёт и журнал аудита.
2. Worker: bad QR получает matching `REJECTED_TERMINAL`; pending очищается, ввод нового QR снова доступен.
3. QR sheet: worker не видит demo CTA/chips; admin в расширенном scan UI открывает четыре настоящих SVG QR из backend seed.
4. Worker summary: Enter создаёт accepted primary, серверный count растёт на один, reload сохраняет count/history, semantic duplicate не увеличивает count и не создаёт вторую строку; история ограничена 10 строками.
5. Rework: новый WIP проходит пайку и сборку; атомарный reject ОТК сохраняет событие+решение и открывает отдельную переделку. После rework primary count сборщика не меняется, rework count растёт, повторный контроль ОТК увеличивается отдельно.
6. Lost reply: backend принимает событие, ответ браузеру намеренно теряется; после reload status lookup находит тот же UUID, локальный pending очищается, в timeline ровно одно route event.
7. Mobile: меню руководителя, длинные русские подписи, карточки KPI и пять рядов проверены при ширине 390 px.
8. Quality gate: зрелость `FINAL` показана как «Оценка завершена», а не как утверждение; при `QUALITY_GATE_FAILED` отображается расчётный KPI и отдельная пометка «не утверждён».
9. Role relevance: на desktop проверены assembly, solder, QC, foreman, planner, auditor, supervisor и admin — worker/QC/FOREMAN получают отдельный topbar без глобального меню, остальные роли — точный состав меню и landing.
10. Direct URL: для закрытого раздела проверено состояние без доступа и отсутствие его page-specific API GET; базовый `/` возвращает worker в `/scan`, QC в `/quality`.
11. Route/config relevance: создание WIP/QR и версий маршрута остаётся у релевантных технологических/admin ролей; auditor сразу открывает разрешённую форму независимого аудита.
12. Mobile worker: при ширине 390 px проверены компактный topbar, крупный QR-ввод, ряд/операция, summary и последние сканы без sidebar/demo CTA.
13. QC atomic: «Годен» и «Брак» сохраняются через единый endpoint; для брака обязательна серверная DEMO-причина, terminal bad QR очищает только matching UUID, checked count и история переживают reload.
14. QC retry: намеренно потерянный браузером ответ восстанавливается status lookup по тому же UUID; count растёт один раз, в журнале одно решение.
15. Cross-role pending: worker pending блокирует QC после reload, QC pending блокирует worker после role switch; чужой payload не очищается автоматически.
16. Mobile QC: при 390 px проверены компактная шапка, QR-поле, две крупные кнопки решения, count и история без sidebar/формул/аудита.
17. FOREMAN own-row: `/foreman` получает server-scoped ряд, совпадающий с `row_id` сессии; UI сверяет roster, primary/rework, problems и reworks с live summary и не показывает названия других рядов.
18. FOREMAN access/reflow: запрещённый прямой URL не запускает page-specific GET; при 390 px нет глобального меню и горизонтального переполнения (`scrollWidth <= clientWidth + 1`).
19. Pending POST/recovery race: worker и QC lost-response сценарии проверяют, что до завершения активного POST не отправляется параллельный status GET; после reload тот же UUID по-прежнему восстанавливается и создаёт ровно один факт/решение.

## Артефакты

- Desktop: `docs/assets/mvp-dashboard.png`.
- Mobile: `docs/assets/mvp-dashboard-mobile.png`.
- Рабочее место сборщика: `docs/assets/mvp-assembly.png` и `docs/assets/mvp-assembly-mobile.png`. Mobile-снимок сделан по viewport при `scrollY=0`.
- Рабочее место ОТК: `docs/assets/mvp-qc.png` и viewport-снимок `docs/assets/mvp-qc-mobile.png`; оба визуально проверены после живого прогона.
- Состояние «Брак» с раскрытым серверным DEMO-справочником причин: `docs/assets/mvp-qc-reject-reason.png`; снимок сделан без отправки нового производственного факта.
- Рабочее место бригадира: `docs/assets/mvp-foreman.png` и viewport-снимок `docs/assets/mvp-foreman-mobile.png`; оба визуально проверены после live-прогона.
- Временные traces/screenshots неуспешных итераций остаются в `frontend/test-results/` только как инженерная диагностика и не считаются итоговым результатом.

## Не заявлено как выполненное

- Пользовательские исследования с реальными работниками завода.
- Ручная проверка экранным диктором.
- Реальный USB/HID-сканер и промышленная сеть.
- Нагрузочный, restore и PostgreSQL-тест — это gate пилота, не локального demo MVP.
