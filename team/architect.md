# Постоянный контекст: архитектор / backend / DevOps

## Роль

- Каноническое имя агента: `/root/architect`.
- Область ответственности: архитектура приложения, backend, модель данных, транзакции, безопасность, импорт, инфраструктура, эксплуатация, оценка поставки и архитектурные ADR.
- Тимлид `/root` распределяет и проверяет работу; backend/DevOps реализацию выполняет `/root/architect`.
- Пользователь 25 октября 2026 года явно разрешил P0-Demo. Созданы код, зависимости, миграции, синтетический seed и тесты; это не разрешение промышленного rollout.

## Устойчивый контекст проекта

- Проект — многопользовательское веб-приложение производственного учёта и расчёта КПД квадрокоптеров, пригодное для портфолио и потенциального заводского пилота.
- MVP — одна площадка, одна модель квадрокоптера и пять рядов: три сборочных, один пайки, один ОТК. Персонал меняется ежедневно; у каждого ряда бригадир; у каждого работника свой компьютер/планшет со сканером.
- Предметная цель — QR-учёт выполнения операций, производственный КПД и отдельная оценка работы ОТК по независимому аудиту решений.
- У деталей свои QR, затем нужен временный WIP QR сборочной единицы (предложение, согласовать) и финальный QR/serial. Нужны genealogy, bind/unbind и неизменяемая история замен.
- Реальные нормы, точные формулы, входные файлы, оргструктура, объемы и NFR будут предоставлены/уточнены позднее.
- Промышленной реализации обязательно предшествует discovery с производством, технологом, ОТК, ИТ/ИБ и пользователями.
- Портфолио использует только явно синтетические данные. Реальные данные, секреты и заводские идентификаторы не попадают в публичные материалы.
- AI не заменяет согласования, UAT, наблюдение пилота и физические/эксплуатационные проверки. Эффект не обещается без замеров.

## Принятые рекомендуемые решения

1. Модульный монолит: FastAPI + Pydantic, SQLAlchemy + Alembic, PostgreSQL; React + TypeScript strict + Vite.
2. Использовать поддерживаемые совместимые ветки Python/FastAPI/Pydantic, SQLAlchemy/Alembic, PostgreSQL, React/TypeScript/Vite. Конкретные версии выбрать compatibility spike и зафиксировать lock-файлами/digest перед кодом; план не является каталогом версий.
3. OpenAPI backend — источник истины; TypeScript-клиент генерируется и проверяется CI.
4. Авторитетная математика выполняется на сервере с Decimal/PostgreSQL `numeric`; никаких скрытых float и округления промежуточных значений.
5. Первичный производственный факт — append-only `OPERATION_EVENT`; текущие состояния и счетчики — изменяемые, пересобираемые проекции. Исправления делаются компенсирующими событиями.
6. QR-событие типизировано по entity (`component`, `wip`, `final_product`) и route step. Детали/WIP не считаются finished units. Маршруты версионируются; нельзя считать, что один продукт последовательно проходит все три сборочных ряда, пока discovery не подтвердит.
7. Genealogy P0 хранит сериализованные component→WIP→final и attach/detach/replace/scrap/rework history; активная деталь не может одновременно принадлежать двум изделиям. Партийные split/merge — P1.
8. UI-сессия связывает worker + workstation + row + operation + shift по authenticated user/assignment. HID-сканер не идентифицирует работника.
9. Idempotency двухуровневая: уникальный `event_id`/request UUID и semantic duplicate `(entity, route version, operation, attempt, completion kind)`. Rework/new attempt открывается разрешенным серверным действием.
10. MVP online-first. Сервер подтверждает каждый scan; клиент хранит ровно один pending scan и UUID, блокирует новые, делает status/retry тем же ID. Pending переживает reload/смену пользователя и не получает другого автора. Полная offline-очередь вне MVP; плохая сеть требует пересмотра scope.
11. Основной плановый компонент — `A_plan` по `Σmin(q_fact_i,q_plan_i)×s_i` внутри фиксированных строк плана; `A_volume=E_fact/E_plan` показывается отдельно. Сверхплан одной строки не закрывает дефицит другой.
11.1. План моделируется как immutable после approval `ProductionPlanVersion` с `PlanLine` по shift/model/route step и optional row; snapshot хранит plan version и уникальное сопоставление факт→строка. `s_i` хранится с единицей, человеко-минуты делятся на 60 для НЧ.
12. Основная производительность использует `H_accounted` из версионируемого TIME_ENTRY ledger с rework и другими утверждёнными потреблёнными категориями. Межскановые интервалы часы не меняют.
13. Производственное качество использует зрелый `E_quality_eligible`; качество решений ОТК — отдельный `Q_decision` только по корректному независимому audit, иначе NULL.
14. Нормы и формулы версионируются по области и времени действия. Утверждённый результат — неизменяемый snapshot событий/назначений/часов, версии нормы/алгоритма и hash входа.
15. Черновики используют optimistic concurrency. Утверждение смены атомарно, но `approval_status` независим от `maturity_state=PROVISIONAL/AWAITING_AUDIT/FINAL` и reason flags.
16. Исправление утверждённого периода — только через регламентированное переоткрытие, компенсирующие события и новую версию snapshot.
17. CSV/XLSX — staging pipeline для согласованных контрактов плана/норм/roster/часов; он не подменяет QR-журнал. MES/1С не обещать до обследования.
18. RBAC разделяет роль и scope; backend проверяет каждый объект; для норм/утверждений предусматривается separation of duties.
19. Auth предпочитает заводской OIDC/IdP. Автономный пилот — server-side session в Secure/HttpOnly/SameSite cookie, Argon2id, CSRF и отзыв сессий.
20. Аудит действий и event journal append-only, но это разные сущности. Технические логи и Prometheus-метрики также отдельны.
21. Стартовая поставка — контейнеры + Docker Compose на локальной Linux VM, TLS reverse proxy и PostgreSQL. Kafka, Kubernetes и микросервисы не нужны.
22. Backup хранится отдельно и считается рабочим после restore drill; при строгом RPO использовать base backup + WAL/PITR. Single-node Compose не объявлять HA.
23. Дорожная карта: Методика → Основа системы → Учёт смен → Расчёт КПД → Отчёты → Пилот. ROM 96–159 человеко-дней до внешнего календарного ожидания.

Основной подробный документ: `docs/02-architecture-and-delivery.md`.

## Открытые вопросы

- Операции и взаимосвязь пяти рядов: последовательность, альтернативы или параллельные ветви.
- Семантика completion scan, тип/настройка scanner input и надежность сети каждого рабочего места.
- Правила component/WIP/final QR, момент печати WIP/final, bind/unbind/replacement и rework transitions.
- Идентичность строк плана/допустимые замены, состав `H_accounted`, `E_quality_eligible`, `rho_target`, Q_min, округление и independent audit protocol ОТК.
- Семантика плана/факта, брака, переделки, повторного ОТК, простоя и незавершенного производства с явными когортами/типами операций.
- Источники истины, стабильные внешние ключи, реальные обезличенные CSV/XLSX и будущие интеграции.
- Структура смен, переход через полночь, смена модели/нормы/route version и переводы работников между рядами.
- Реальная оргструктура, матрица RBAC, право переоткрытия, принцип двух лиц и требования ЭП.
- Наличие OIDC/AD/LDAP, PKI, SIEM, registry, backup и политики ИБ.
- Объемы, конкурентность, retention, целевые p95, SLA, RPO/RTO и владелец эксплуатации.
- Подтверждение пригодности online-first; если сеть плохая — отдельное решение и переоценка полноценного offline вне MVP.
- Критерии успеха пилота и методика измерения эффекта.

## Продолжение работы

1. Текущий runnable backend: FastAPI/SQLAlchemy/Alembic, persistent SQLite DEMO adapter, API `127.0.0.1:8010`; порт 8000 занят чужим LeadFlow и не должен останавливаться.
2. Проверено: 76 backend tests, migration+seed, HTTP scan+retry/negative terminal ACK, atomic QC inspection, configurable route/entity включая FINAL, личная shift activity работника, row KPI пяти рядов, restart persistence и SQLite backup/restore. PostgreSQL Compose остаётся целевым, но локально не проверен из-за отсутствия Docker/psql.
3. One-command lifecycle проверен: `start-demo.cmd` → API ready + UI HTTP 200 → `stop-demo.cmd` → повторный start. Stop сверяет PID, полный executable/workspace command token и creation time; Vite использует strictPort. UI `127.0.0.1:5173` и API `127.0.0.1:8010` оставлены работающими; чужой LeadFlow на 8000 не затронут. Финальный browser E2E завершает `/root/ux_quality`; backend больше не перезапускать без нового дефекта/поручения.
4. Сохранять server-side auth/RBAC/CSRF, canonical payload hash+actor guard, одну транзакцию event+projection, DB partial unique genealogy, независимый ОТК audit и frozen snapshot.
5. На discovery оформить оставшиеся реальные решения как ADR/decision log; каждому вопросу назначить владельца и срок.
6. На реальных устройствах проверить scanner input, pending retry/status, reload, смену пользователя и потерю сети; SQLite тест не заменяет PostgreSQL concurrency/load/restore drill.

## Сверка ролевого интерфейса и server RBAC от 25 октября 2026

- Выполнен read-only review `app/security.py`, seed-ролей и guards фактических API. Backend не менялся, работающие UI `127.0.0.1:5173` и API `127.0.0.1:8010` не перезапускались; чужой сервис на 8000 не затрагивался.
- UI relevance намеренно строже server capabilities и задаётся явной матрицей ролей. `read_entities` у работников и ОТК остаётся технической зависимостью сканирования, поиска QR, pending/status и rework lookup, но само по себе не открывает пункт «Изделия». Аналогично `view_reports` не является автоматическим разрешением показать «Сводку» или «Маршруты».
- Согласованный видимый контур: WORKER — сканирование; QC — сканирование и ОТК/переделки; FOREMAN — сводка, сканирование, изделия, состав/часы, ОТК/переделки, отчёты и конфигурация только для легитимного создания WIP/final QR; PLANNER — состав/часы, нормы/план, отчёты; AUDITOR — изделия, ОТК/переделки, отчёты, аудит; SUPERVISOR — сводка, изделия, отчёты, аудит; ADMIN — все разделы; TECHNOLOGIST — маршруты/QR, нормы/план, изделия, отчёты. В seed нет отдельной учётной записи TECHNOLOGIST.
- Для FOREMAN unified-экран конфигурации сохраняется из-за фактического права `manage_genealogy` и P0-сценария POST `/tracked-entities`; маршрут на этом экране только контекст выбора опубликованной версии. Создание/публикация маршрутов остаётся за `manage_standards` (TECHNOLOGIST/ADMIN).
- Изолированная проверка на временной SQLite БД подтвердила для WORKER: 9 защищённых read endpoints (`dashboard`, `shifts`, `plans`, `standards`, `route-versions`, `assignments`, `time-entries`, `employees`, `audit`) возвращают 403; 9 чужих mutations норм/маршрутов/QR/genealogy/часов/качества/audit/rework/approval возвращают 403; 7 технических reads для bootstrap/work session/entity/quality/rework остаются доступны. Это проверка фактических guards, а не утверждение заводской матрицы.
- Business-RBAC дефект, требующий изменения API в рамках текущего запроса, не найден. Seed-роль FOREMAN сейчас без `row_id` и тем самым демонстрационно охватывает все пять рядов; для реального пилота иерархический object scope/IDOR необходимо утвердить и проверить отдельно, не маскируя его UI-скрытием.

## Восстановление demo-сервисов 25 октября 2026

- После сообщения UX `ECONNREFUSED` ownership-файл указывал на уже отсутствующие backend/frontend PID; listeners 8010/5173 отсутствовали. Stale state очищен только штатным `stop-demo.ps1`, затем выполнен `start-demo.ps1 -NoBrowser` без reset: seed сообщил `DEMO already exists; unchanged`.
- Фактически подтверждено после запуска: API `http://127.0.0.1:8010/api/v1/health/ready` возвращает `ready/sqlite`, UI `http://127.0.0.1:5173` — HTTP 200. Порт 8000 не имел listener до/после recovery и не затрагивался.
- Обнаружен lifecycle-дефект: PowerShell `ConvertFrom-Json` превращал ISO creation timestamp в `DateTime`, а `[string]` терял доли секунды, из-за чего будущий `stop-demo.ps1` мог fail closed даже для owned PID. Исправлена только нормализация ожидаемого времени в UTC round-trip format; работающие процессы не перезапускались после patch. Dry identity validation подтвердила executable, полный workspace command token и creation time обоих owned roots.

## Упрощённый экран работника: backend-контракт

- Добавлен узкий `GET /api/v1/me/shift-activity?limit=10` с capability `scan`. Клиент не передаёт `employee_id` или `shift_id`: actor берётся из auth, смена — текущая `RUNNING`; все рабочие сессии и переводы этого user внутри смены агрегируются сервером.
- `primary_completed` считает только эффективные `ACCEPTED + COMPLETE + PRIMARY`; accepted correction любого автора погашает original. Rework считается отдельно, retry/semantic duplicate новой строки не создают, pending/rejected/correction не увеличивают primary. Это число операций, не готовых квадрокоптеров и не персональный KPI.
- `recent_events` содержит не более десяти последних `COMPLETE` journal rows actor/shift. Correction row не изображается как скан; original получает `corrected=true` и effective `display_status=CORRECTED`. Отрицательные terminal responses, отклонённые до записи `OPERATION_EVENT`, остаются transient UI-ответами и не заявляются как долговечная история попыток.
- Контекст строки/операции берётся из последней незавершённой WorkSession с активным assignment; при её отсутствии `context=null`, а серверные counts/history сохраняются после reload или открытия новой сессии.
- Фактически проверено: 62/62 backend tests; новые тесты покрывают изоляцию другого работника и другой смены, retry, rework, pending, correction другим actor, status/limit и отсутствие активной смены. Контракт описан в `docs/04-api.md` и согласован с `/root/ux_quality` и `/root/process_analyst`.
- После safe lifecycle restart без reset выполнен live smoke под `assembly1`: финальные ключи ответа без suffix (`primary_completed`, `rework_completed`, `corrected_primary`), context и recent history получены из persistent SQLite. API 8010 `ready/sqlite`, UI 5173 HTTP 200, ownership identity backend/frontend прошла; UX получил `FINAL READY`, дальнейших рестартов до его E2E не делать.

## Упрощённый экран ОТК: атомарный backend-контракт

- Без изменения schema добавлены `POST /api/v1/qc-inspections`, `GET /qc-inspections/{id}/status`, `GET /me/qc-shift-activity?limit=10` и `GET /qc-defect-reasons`. `inspection_id` хранится как `QualityDecision.request_id`; новый completion использует тот же UUID как `OperationEvent.id`, а безопасный reuse legacy completion получает idempotency receipt в atomic `AuditEvent` с payload hash/actor.
- Одна транзакция валидирует active QC session/assignment, exact route/entity и rework state, создаёт/reuses `ACCEPTED COMPLETE`, `QualityDecision`, projection/rework transition и audit. REJECT требует synthetic server catalog; ACCEPT запрещает defect reason. Клиент не задаёт attempt: FIRST_PASS/PRIMARY или REINSPECTION/REWORK выводятся сервером.
- Safe retry проверяет UUID + canonical payload hash + original actor. После unique conflict backend повторно читает decision/receipt: совпавшая команда возвращается duplicate success; payload/actor/in-progress не дают ложного terminal reject. Valid NOT_FOUND pending только status/retry same UUID; cancel без durable tombstone сознательно не добавлен. Corrupt local JSON разрешается generic audited foreman/admin action и не выдаётся за отмену server request.
- READY_FOR_QC становится REINSPECTED вместе с решением независимо от ACCEPT/REJECT; повторный reject открывает новый цикл только отдельным rework action от latest effective REJECT. Rework проверяет same route и отсутствие active order; FINALIZE использует последнее effective control decision, поэтому старый ACCEPT не маскирует поздний REJECT.
- Summary считает effective decisions actor/active shift и отдельно first-pass/reinspection; reject — выполненная проверка, а не штраф. Recent history сохраняет corrected решения с `corrected=true/display_status=CORRECTED`, но они не входят в counts и не являются основанием rework. `bootstrap.route_steps` теперь содержит `allows_rework`.
- Фактически проверено: 69/69 backend tests; новый targeted suite 7/7 и независимые legacy rework/audit/finalize 2/2. Legacy `/quality/decisions` сохранён для compatibility и остаётся старым двухшаговым путём; новый UI использует только atomic command.
- После coordinated safe restart без reset live smoke подтвердил API 8010 `ready/sqlite`, UI 5173 HTTP 200, `allows_rework` в bootstrap, catalog из четырёх synthetic причин, QC summary exact shape/corrected marker и unknown status `NOT_FOUND/terminal=false/retryable=true`; ownership identity обоих процессов прошла. UX получает `FINAL READY`; backend после этого frozen до конкретного regression.

## Упрощённый экран бригадира: собственный ряд

- Добавлен read-only `GET /api/v1/me/foreman-shift-summary?limit=10`: требуется `view_reports` и explicit роль `FOREMAN`, клиент не передаёт row/shift/employee. Канонический scope — единственный `UserRole.row_id`; legacy compatibility fallback допускает только один row активного назначения самого бригадира, при 0/>1 ответ 409 без глобального доступа.
- Fresh synthetic seed связывает `foreman → DEMO-ASM-01`. Для существующей persistent DEMO БД добавлен idempotent upgrade без reset с `DEMO_FOREMAN_SCOPE_UPGRADED` audit; explicit non-null scope он не перезаписывает.
- Roster включает active/ended assignments своего ряда и не заявляет online presence. Primary/rework считаются отдельно по историческому `OperationEvent → WorkSession.row_id`, только effective ACCEPTED COMPLETE, с correction anti-exists; перевод сотрудника не переписывает прошлый выпуск.
- Для definite terminal rejection после authenticated owned active work session создаётся `OPERATION_SCAN_REJECTED` AuditEvent с request UUID, payload hash, actor/shift/row/session/step/QR/code. Повтор exact UUID/body воспроизводит ошибку без нового issue; другой actor и changed payload не получают чужой результат. Audit receipt не создаёт OperationEvent, projection или credit. Shift closed/foreign session/network/401 не изображаются row issue.
- `problems` — read-only история durable NEEDS_REVIEW events и server rejection receipts, не удалённые pending других станций; `allowed_actions=[]`. `reworks` включает exact target row либо effective accepted rework evidence на row в окне до следующего order той же entity+step; NULL-row order без факта не приписывается всем assembly-рядам.
- Generic corrupt-local acknowledgement остаётся существующим `resolve_pending` endpoint для FOREMAN/ADMIN и не считается отменой server request. Valid worker/QC pending следует status/retry правилам; `NOT_FOUND` не terminal.
- Фактически проверено: targeted foreman 7/7 и полный backend suite 76/76 PASS; независимый review foreman+scan 10/10 и отдельный temp-сценарий двух NULL-row rework cycles PASS. Покрыты row2 error/output isolation, actor guard, transfer history, correction/rework counters, dedup rejected receipt и cycle-bounded rework attribution.
- Coordinated safe restart выполнен без reset: startup применил scope upgrade, audit присутствует ровно один раз; API 8010 `ready/sqlite`, UI 5173 HTTP 200, role scope/summary дают `DEMO-ASM-01`. Live exact retry одного rejected UUID дважды вернул тот же `ENTITY_NOT_FOUND`, а foreman history содержит одну `SCAN_REJECTED/REJECTED_TERMINAL` запись без production credit/actions. Точный контракт описан в `docs/04-api.md`; UX получает `FINAL READY`, backend после этого frozen до конкретного regression.

## Git и CI для портфолио

- Локальный репозиторий инициализирован на ветке `main`, remote и commit пока отсутствуют. Git identity пользователя не задана и не изменялась; initial commit разрешено делать только после финального сигнала тимлида одноразовой служебной подписью `Codex Automation <codex@localhost>` через `git -c`, без изменения global/local config.
- `.gitignore` исключает зависимости, caches/build/test output, `.run`, локальные DB/backups, secrets, logs и traces. Перед commit повторить staged-only проверку файлов и сигнатур секретов без вывода содержимого.
- `.github/workflows/ci.yml` подготовлен для `workflow_dispatch`, push `main` и pull request: locked backend pytest, frontend typecheck/build, затем isolated migrated+seeded SQLite E2E. GitHub Actions фактически не запускался, потому что remote/публикации нет.
- Локальное воспроизведение workflow в удалённой после проверки `.ci-verify-tmp` подтверждено: fresh backend `76 passed`; fresh frontend `npm ci`, typecheck/build PASS; isolated Playwright `16 passed, 12 skipped` на 5174/8011. Live 5173/8010 не перезапускались и их данные не использовались.
- Во время isolated E2E найден и исправлен frontend race active POST против recovery status GET для worker/QC pending. Финальный regression требует ноль status GET до reload, затем lost-response recovery и ровно один серверный факт/решение; полный повторный suite прошёл.
- Следующий шаг: дождаться `FINAL READY` тимлида по README/кейсу/видео, затем staged-only scan, initial commit со служебной one-command identity, проверка clean status. Remote/push и hosted CI без отдельного решения не выполнять.

## 25 октября 2026 — release-ready проверка для GitHub

- По новой явной авторизации проверены Git-visible snapshot и единственный commit: private-key/cloud/GitHub/OpenAI token signatures, absolute user paths, personal email и локальные DB/log/backup/env в tracked-дереве не найдены. `.env.compose.example` и `Demo2026!` — явно маркированные synthetic localhost config/credentials, не секреты.
- README больше не содержит мгновенно устаревающее утверждение об отсутствии remote; добавлены localhost-only warning, граница hosted CI и явный статус отсутствия open-source license. `.gitattributes` фиксирует endings Windows launch scripts и binary media.
- Это подготовка публичных исходников, не production rollout и не допуск к недоверенному hosted demo. Remote/push выполняет `/root`; после push нужно проверить первый hosted Actions run.

## 25 октября 2026 — первый hosted CI

- GitHub Actions run `40231696377` на commit `69f33db` подтвердил Backend tests и Frontend checks, но Isolated live E2E дал `15 passed / 12 skipped / 1 failed`: baseline worker-счётчик был прочитан как loading placeholder, `Number(...)` вернул `NaN`, тогда как после server acknowledgement DOM уже содержал `2`.
- E2E harness не ослаблен: общий `readNumericCount` сначала ждёт строгий DOM-текст `/^\d+$/`, затем преобразует его в число; исходные проверки exact increments/reload/dedup сохранены. Helper применён ко всем аналогичным worker/QC counts.
- Фактически проверено на отдельных SQLite/портах, без live demo: frontend typecheck PASS; исходно упавший desktop-сценарий `1 passed`; полный fresh migrated+seeded Playwright `16 passed / 12 intentional skips / 0 failed`. Временно перезаписанные harness PNG восстановлены из clean HEAD. После push нужен новый hosted run; PASS заранее не заявляется.

