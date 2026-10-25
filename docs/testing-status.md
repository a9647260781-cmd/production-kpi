# Фактический статус проверок P0-Demo

Дата: 25 октября 2026 года. Среда: Windows, Python 3.12.2, Node 20.19.0. Данные только синтетические.

## Подтверждено

- `.venv` воспроизводимо установлена из `requirements.lock`.
- `python -m pytest -q`: **76 passed**, одно внешнее deprecation-warning FastAPI TestClient/httpx2, ошибок нет.
- Alembic initial migration применена к пустой временной SQLite БД; deterministic seed создал 10 demo users и доменные данные.
- Real HTTP API на `127.0.0.1:8010`: health ready, login, dashboard, scan, retry того же UUID, terminal negative ACK, route violation, genealogy, rework/reinspect, independent audit, approval snapshot и CSV.
- Accepted scan пережил остановку/повторный запуск API; повтор UUID не создал второй факт.
- SQLite backup создан через online backup API, integrity checked, восстановлен при остановленном API; accepted event сохранился после restore/restart.
- Dashboard возвращает пять row metrics: A/P/H для трёх сборочных рядов и пайки, отдельный Q ОТК; неатрибутируемый row quality остаётся `NULL` с причиной.
- Configurable route/entity API создаёт draft, публикует immutable route, регистрирует component/WIP/final QR; произвольная assembly operation проходит server route validation.
- `start-demo.ps1` проверен полным циклом: start → API ready + UI HTTP 200 → stop → повторный start. Stop сверяет PID, полный executable/workspace command token и process creation time; чужой `LeadFlow API` на порту 8000 остался работающим.
- После внешнего завершения ранее owned PID stale ownership был безопасно очищен штатным `stop-demo.ps1`, затем persistent demo без reset снова запущен: API `8010` вернул `ready/sqlite`, UI `5173` — HTTP 200. Порт 8000 в момент восстановления уже не имел listener и скриптами не затрагивался.
- При recovery выявлено и исправлено преобразование ISO timestamp из ownership JSON в PowerShell `DateTime`: `stop-demo.ps1` теперь нормализует ожидаемое время обратно в UTC round-trip format до сравнения. Без остановки текущих процессов dry identity check подтвердил совпадение executable, полного command token и creation time для backend/frontend.
- Frontend production build (`tsc -b && vite build`) выполнен успешно.
- Worker shift activity API проверен на actor isolation, исключение другой смены/другого работника, idempotent retry без прироста, отдельный rework, непринятый pending без прироста, correction другим actor и `404` без активной смены.
- После safe lifecycle restart без reset live smoke `assembly1 → GET /me/shift-activity` подтвердил финальные поля `primary_completed/rework_completed/corrected_primary`, текущий row/route-step и persistent recent history; API остался `ready/sqlite`, UI вернул HTTP 200, ownership identity обоих процессов совпала.
- Atomic QC API проверен: UUID/body/actor idempotency, lost-response status, terminal/non-terminal acknowledgements, reason catalog, wrong route, rollback без частичных event/decision/projection, safe reuse собственного legacy completion, произвольный код QC step, primary при `allows_rework=false`, server-derived reinspection, latest reject/rework linkage, summary isolation и corrected history. Независимый domain review подтвердил targeted 7/7 и legacy rework/audit/finalize 2/2.
- После safe restart без reset live smoke подтвердил API `ready/sqlite`, UI HTTP 200, `bootstrap.route_steps[].allows_rework`, четыре synthetic defect reasons, QC summary с expected count keys/corrected marker и unknown inspection status `NOT_FOUND + terminal=false + retryable=true`; ownership identity backend/frontend совпала.
- Foreman self-row API проверен отдельным suite 7/7: server scope и unique-assignment fallback, отсутствие глобального fallback, active+ended roster, effective primary/rework counters, correction exclusion, row2 isolation, actor-bound rejected UUID, сохранение row1 output после transfer, durable/deduplicated route rejection без production credit и conservative rework attribution в пределах цикла. Независимый review добавил foreman+scan 10/10 и temp-сценарий двух rework cycles на разных рядах.
- После coordinated safe restart без reset startup сообщил `DEMO foreman scope upgraded`; в persistent БД ровно один upgrade audit. Live API/UI вернули `ready/sqlite` и HTTP 200, role scope и summary row совпали с `DEMO-ASM-01`. Двукратный exact retry неизвестного QR дал один durable `SCAN_REJECTED/REJECTED_TERMINAL` в foreman history, `allowed_actions=[]`, production count не изменился.
- Локальный Git-репозиторий инициализирован на ветке `main`; remote и commit отсутствуют, глобальная/пользовательская Git identity не изменялась. Кандидаты initial commit проверены: 112 файлов до финальных документационных изменений, подозрительных имён файлов и совпадений по сигнатурам private key/AWS/GitHub/Slack/OpenAI token не найдено. Проверка не выводила содержимое потенциальных секретов.
- `.gitignore` фактически исключает локальные `.venv`, `node_modules`, Python/pytest/Vite/Playwright caches и output, `.run`, SQLite DB, backups, secrets, logs и traces. Изолированная проверочная копия `.ci-verify-tmp` после прогона удалена и в commit не входит.
- Подготовлен `.github/workflows/ci.yml` с ручным `workflow_dispatch`, push в `main` и pull request: отдельные jobs backend `pytest`, frontend typecheck/build и live E2E на мигрированной/seeded временной SQLite. Hosted GitHub Actions не запускался и CI не заявляется как удалённо подтверждённый PASS.
- Команды workflow воспроизведены локально в изолированной копии без чтения, reset или перезапуска live DB/UI/API: fresh Python venv + locked install, `76 passed` backend; fresh `npm ci`, typecheck и production build — PASS; Alembic + synthetic seed — PASS; Playwright на отдельных `5174 → 8011` — `16 passed, 12 skipped`, ошибок нет. Пропуски — намеренное разделение desktop/mobile сценариев, а не скрытые падения.
- Изолированный E2E выявил гонку: recovery status GET мог опередить активный POST нового scan и затереть ответ semantic duplicate как `NOT_FOUND`. Frontend owner добавил guard UUID активной submission для worker и QC; регрессия проверяет отсутствие status GET до reload и сохранение ровно одного факта/решения. Полный повторный E2E после исправления прошёл.

## Не проверено в этой среде

- Docker и `psql` отсутствуют, поэтому `compose.postgres.yml`, PostgreSQL migration, concurrent locking, `pg_dump/pg_restore` и resource limits подготовлены, но локально не исполнялись.
- Нет реальных сканеров, заводской сети, IdP, TLS/PKI, SIEM, MES/1С, production backup storage и мониторинга.
- Нет load/soak/HA/security penetration испытаний и реального UAT.
- Нет Git remote и фактического hosted GitHub Actions run; workflow проверен только локальным воспроизведением команд в текущей Windows-среде. Linux runner и публикация репозитория остаются планом до решения пользователя.
- Методика, нормы, маршруты, QR и целевые показатели demo синтетические; промышленный эффект не измерялся.

## Команды проверки

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe -m app.seed
.venv\Scripts\python.exe -m app.backup --backup
```

Пользовательский путь запуска/остановки: `start-demo.cmd` и `stop-demo.cmd`. Скрипт остановки использует ownership-файл `.run/demo-processes.json` и не останавливает неизвестные процессы.
