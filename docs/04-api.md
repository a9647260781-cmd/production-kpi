# API демонстрационного MVP

Статус: рабочий контракт P0-DEMO. Все данные seed синтетические. Базовый URL на этой машине: `http://127.0.0.1:8010/api/v1` (порт 8000 уже занят другим локальным приложением).

Интерактивная схема доступна на `/docs`, OpenAPI — `/openapi.json`. API является единственным источником расчётов: frontend не пересчитывает КПД.

## Общие правила

- JSON использует UTF-8 и `snake_case`.
- `Decimal` возвращается строкой (`"0.95"`), неизвестное значение — `null`.
- После login сервер ставит HttpOnly cookie. Все изменяющие запросы, кроме login, требуют заголовок `X-CSRF-Token`.
- `GET /auth/me` возвращает актуальный `csrf_token`, поэтому retry после reload не требует нового login.
- Ошибка: `{"error":{"code":"...","message":"...","field_errors":[],"trace_id":"..."}}`.
- Списки: `{"items":[],"total":0,"next_cursor":null}`.
- Событийные enum в P0 регистрозависимы: `COMPLETE`, `PRIMARY`, `REWORK`, `ACCEPTED`, `NEEDS_REVIEW`, `CANCELLED`.
- Время приёма события задаёт сервер в UTC. Фиксированная дата DEMO-смены — бизнес-дата сценария, а не подмена серверных часов.

## Демо-вход

Общий пароль только для синтетического локального набора: `Demo2026!`.

Пользователи: `assembly1`, `assembly2`, `assembly3`, `solder`, `qc`, `foreman`, `auditor`, `planner`, `supervisor`, `admin`.

```http
POST /api/v1/auth/login
Content-Type: application/json

{"username":"assembly1","password":"Demo2026!"}
```

`user` содержит `roles`, `scopes`, канонический список `capabilities` и `csrf_token`. Server authorization всегда проверяет capability и объектный scope. Видимость разделов UI дополнительно использует более строгую явную матрицу релевантности ролей: технический `read_entities`, необходимый сканеру, сам по себе не показывает работнику весь раздел изделий.

## Маршруты

| Метод и путь | Назначение | Capability |
|---|---|---|
| `GET /health/live`, `/health/ready` | liveness/readiness | public |
| `POST /auth/login`, `GET /auth/me`, `POST /auth/logout` | cookie-сессия | authenticated |
| `GET /bootstrap` | активная смена, 5 рядов, станции, маршрут (`allows_rework` включён), sample QR | authenticated |
| `GET /me/shift-activity?limit=10` | личные счётчики операций и последние сканы активной смены | `scan`, actor из auth |
| `GET /qc-defect-reasons` | синтетический справочник причин брака для dropdown | `quality_decide` |
| `POST /qc-inspections` | атомарно сохранить QR-контроль и решение ОТК | `quality_decide` + CSRF |
| `GET /qc-inspections/{uuid}/status` | durable status/retry атомарной проверки ОТК | исходный контролёр |
| `GET /me/qc-shift-activity?limit=10` | личные итоги и последние проверки ОТК активной смены | `quality_decide`, actor из auth |
| `GET /me/foreman-shift-summary?limit=10` | собственный ряд бригадира: назначения, операции, зафиксированные ошибки и переделки | `view_reports` + роль `FOREMAN`, row из server scope |
| `GET /dashboard` | ряды и серверный расчёт | `view_reports` |
| `GET /employees` | справочник для roster | `manage_assignments` |
| `GET /shifts` | список смен | `view_reports` |
| `GET,POST /route-versions`, `POST /route-versions/{id}/publish` | draft/publish настраиваемого маршрута | read/`manage_standards` |
| `GET,POST /tracked-entities` | регистрация новых QR component/WIP/final | read/`manage_genealogy` |
| `GET,POST,DELETE /work-sessions` | контекст worker+station+row+operation+shift | `scan` |
| `POST /operation-events` | подтверждение операции | `scan` |
| `GET /operation-events/{uuid}/status` | durable pending/retry status | owner/foreman |
| `POST /operation-events/{uuid}/resolve` | отмена `NEEDS_REVIEW` | `resolve_pending` |
| `POST /operation-events/resolve-local-corruption` | аудируемое удаление повреждённого local pending | `resolve_pending` |
| `GET /entities/by-qr/{qr}` | найти сущность | `read_entities` |
| `GET /entities/{id}/timeline` | единая route/genealogy/quality timeline | `read_entities` |
| `POST /genealogy/actions` | `ATTACH/DETACH/REPLACE/FINALIZE/SCRAP` | `manage_genealogy` |
| `GET /assignments`, `POST /shifts/{id}/assignments` | сменный состав | `manage_assignments` |
| `GET,POST /time-entries` | ledger человеко-часов | `manage_time_entries` |
| `GET,POST /plans` | неизменяемые версии плана | read/manage plans |
| `GET,POST /standards` | версии норм | read/manage standards |
| `GET,POST /quality/decisions` | решения ОТК | read/`quality_decide` |
| `GET,POST /quality/audits` | независимый аудит решений | read/`quality_audit` |
| `GET,POST /rework-orders` | разрешения rework | read/`manage_rework` |
| `GET /shifts/{id}/calculation` | live server-side KPI | `view_reports` |
| `POST /shifts/{id}/approve` | атомарный frozen snapshot | `approve_shift` |
| `GET /reports/{id}` | frozen snapshot после approval, иначе live | `view_reports` |
| `GET /reports/{id}.csv` | CSV того же snapshot | `view_reports` |
| `GET /audit` | append-only журнал действий | `view_audit` |

## Scan и online-first pending

```json
{
  "event_id": "client-generated-uuid-v4",
  "work_session_id": "uuid",
  "subject_qr": "DEMO-WIP-004",
  "event_type": "COMPLETE",
  "attempt_type": "PRIMARY",
  "attempt_no": 1,
  "occurred_at_device": null
}
```

Клиент хранит не более одного pending scan вместе с полным canonical body и исходным worker/context. До ответа сервера новые сканы запрещены.

- Повтор того же UUID, actor и body возвращает исходный результат с `duplicate=true`.
- Тот же UUID с другим actor даёт `403 EVENT_OWNER_MISMATCH`.
- Тот же UUID с изменённым body даёт `409 IDEMPOTENCY_PAYLOAD_MISMATCH`.
- Новый UUID для той же semantic completion возвращает `SEMANTIC_DUPLICATE` и не увеличивает факт.
- Нарушение маршрута возвращает `409 ROUTE_VIOLATION`.
- Событие и materialized projection записываются одной транзакцией.
- Offline-очередь нескольких событий вне P0. При плохой сети scope пересматривается после discovery.
- Route step принимается только из той же опубликованной версии маршрута, что закреплена за QR; тип сущности также проверяется сервером.

Гарантированно неисполненная domain-проверка сохраняет HTTP 4xx и возвращает рядом с `error` отрицательное подтверждение: `submission={event_id,status:"REJECTED_TERMINAL",code,message,accepted:false,terminal:true,retryable:false,next_steps:["FIX_AND_RESCAN"]}`. Клиент очищает pending только при совпадении UUID и `terminal=true`. Network/5xx/401, чужое авторство и `GET status → NOT_FOUND` не доказывают отказ: у них terminal отсутствует или равен `false`, pending сохраняется.

Ответ содержит `status`, `code`, `server_received_at`, `review_id`, `retryable`, `next_steps`, `duplicate` и идентификаторы принятого события. Неизвестный status после потери ответа проверяется через `GET .../status` с тем же UUID.

### Личная активность работника за смену

`GET /me/shift-activity?limit=10` не принимает `employee_id` или `shift_id`: сервер использует authenticated user и текущую `RUNNING` смену. `limit` находится в диапазоне 1–10. Если активной смены нет, ответ — `404 ACTIVE_SHIFT_NOT_FOUND`, а не нулевые показатели.

```json
{
  "shift": {"id": "uuid", "code": "DEMO-SHIFT-2026-10-25-D", "production_date": "2026-10-25"},
  "employee": {"id": "uuid", "display_name": "Оператор сборки 1"},
  "context": {
    "work_session_id": "uuid",
    "row": {"id": "uuid", "code": "DEMO-ASM-01", "name": "Сборка 1"},
    "route_step": {"id": "uuid", "code": "DEMO-ASSEMBLE", "name": "Сборка"}
  },
  "primary_completed": 1,
  "rework_completed": 0,
  "corrected_primary": 0,
  "recent_events": [
    {
      "id": "uuid",
      "event_id": "uuid",
      "subject_qr": "DEMO-WIP-001",
      "attempt_type": "PRIMARY",
      "event_type": "COMPLETE",
      "status": "ACCEPTED",
      "display_status": "ACCEPTED",
      "code": "EVENT_ACCEPTED",
      "outcome": "COMPLETED",
      "server_received_at": "2026-10-25T06:01:00+00:00",
      "corrected": false,
      "row": {"id": "uuid", "code": "DEMO-ASM-01", "name": "Сборка 1"},
      "route_step": {"id": "uuid", "code": "DEMO-ASSEMBLE", "name": "Сборка"}
    }
  ],
  "note": "Счётчики операций сотрудника не являются количеством готовых изделий или персональным KPI."
}
```

- `primary_completed` считает только уникальные server-journal rows `ACCEPTED + COMPLETE + PRIMARY` текущего actor в активной смене. Rework, correction, pending/rejected rows и исходный scan, погашенный accepted correction, не увеличивают число. Idempotent retry и semantic duplicate не создают новую строку.
- `rework_completed` считает эффективные `ACCEPTED + COMPLETE + REWORK` отдельно; он не увеличивает primary.
- `corrected_primary` показывает число primary completion этого actor, погашенных accepted correction любого автора.
- `recent_events` — не более десяти последних `COMPLETE` journal rows этого actor и смены, newest-first по авторитетному `server_received_at`. Correction row сам не является QR-сканом и в список не входит; исходный scan получает `corrected=true` и `display_status="CORRECTED"`. Accepted rework получает `display_status="REWORK"`; иначе `display_status` повторяет фактический journal `status`.
- Контекст выбирается из последней незавершённой рабочей сессии с активным назначением. Если такой сессии нет, `context=null`, но сохранённые за смену счётчики и история не теряются после reload или открытия новой сессии.
- Гарантированно отклонённые до записи scanner requests не сохраняются в `OPERATION_EVENT` и не входят в личный счётчик работника. После проверки owned work session сервер сохраняет отдельный audit receipt для row-scoped истории бригадира; network/401/foreign-session и локальные pending других станций из этого не выводятся.

### Сводка собственного ряда бригадира

`GET /me/foreman-shift-summary?limit=10` не принимает `row_id`, `employee_id` или `shift_id`. Сервер требует одновременно capability `view_reports` и роль `FOREMAN`, затем выбирает ровно один `UserRole.row_id`. Для legacy DEMO без scope временно допускается только ровно один ряд активного назначения самого бригадира в текущей смене; отсутствие или неоднозначность дают `409 FOREMAN_ROW_SCOPE_MISSING/AMBIGUOUS`, а не доступ ко всему цеху. Idempotent DEMO-upgrade закрепляет `foreman → DEMO-ASM-01` без reset и оставляет audit event.

```json
{
  "shift": {"id": "uuid", "code": "DEMO-SHIFT-2026-10-25-D", "production_date": "2026-10-25"},
  "row": {"id": "uuid", "code": "DEMO-ASM-01", "name": "Сборка 1", "category": "ASSEMBLY"},
  "roster": [{
    "assignment_id": "uuid",
    "employee": {"id": "uuid", "display_name": "Оператор сборки 1", "personnel_no": "DEMO-E-01", "status": "ACTIVE"},
    "workstation": {"id": "uuid", "name": "Терминал Сборка 1"},
    "route_step": {"id": "uuid", "name": "Сборка"},
    "assignment_status": "ACTIVE",
    "starts_at": "2026-10-25T05:00:00+00:00",
    "ends_at": "2026-10-25T13:00:00+00:00"
  }],
  "primary_completed": 1,
  "rework_completed": 0,
  "problems": [{
    "id": "audit-or-event-uuid",
    "kind": "SCAN_REJECTED",
    "code": "ROUTE_VIOLATION",
    "qr": "DEMO-WIP-004",
    "operation": {"id": "uuid", "name": "Сборка"},
    "worker": {"id": "uuid", "display_name": "Оператор сборки 1"},
    "occurred_at": "2026-10-25T10:00:00+00:00",
    "status": "REJECTED_TERMINAL",
    "message": "Ожидалась другая позиция маршрута",
    "allowed_actions": []
  }],
  "reworks": [{
    "id": "uuid",
    "qr": "DEMO-WIP-002",
    "reason": "Повторить сборочную операцию",
    "requested_route_step": {"id": "uuid", "name": "Сборка"},
    "status": "READY_FOR_QC",
    "created_at": "2026-10-25T09:00:00+00:00",
    "allowed_actions": []
  }],
  "note": "Состав отражает назначения, а не присутствие онлайн; счётчики — операции ряда, не готовые изделия и не персональный KPI."
}
```

- `roster` содержит активные и завершённые назначения собственного ряда за смену. Employee status — статус справочника, не присутствие онлайн.
- `primary_completed` и `rework_completed` считаются раздельно по историческому `OperationEvent → WorkSession.row_id`: перевод сотрудника не переписывает прежнюю атрибуцию. Учитываются effective `ACCEPTED + COMPLETE`, accepted correction исключает original; duplicate/rejected/pending не дают credit.
- `problems` — не очередь удалённых pending. Это последние долговечные `NEEDS_REVIEW` events и audit receipts гарантированно отклонённых server scans после authenticated owned work session; одинаковый request UUID/body/code не размножает историю. Поле `allowed_actions=[]`: экран пока read-only и не объявляет ошибку «нерешённой».
- `reworks` включает точный `requested_route_step.row_id` собственного ряда. Альтернативный assembly step с `row_id=null` появляется только после effective accepted rework-события этого цикла на данном ряду; окно ограничено следующей заявкой той же entity+step. Неоднозначная неназначенная переделка не приписывается всем трём сборочным рядам.
- Browser-local worker/QC pending и повреждённые local records UI показывает отдельно только для текущего браузера. `NOT_FOUND` не отменяет valid pending; generic `/operation-events/resolve-local-corruption` доступен `FOREMAN/ADMIN` через `resolve_pending` и подтверждает только удаление повреждённого local JSON.

### Атомарная проверка ОТК

Новый простой экран ОТК использует одну команду вместо двух пользовательских действий «скан → отдельное решение»:

```json
{
  "inspection_id": "client-generated-uuid-v4",
  "work_session_id": "uuid",
  "subject_qr": "DEMO-WIP-004",
  "decision": "REJECT",
  "defect_code": "DEMO-ASSEMBLY",
  "occurred_at_device": null
}
```

Сервер берёт actor из auth и атомарно валидирует active shift/session/assignment, ряд ОТК, exact route step, entity type/version и rework state; затем создаёт либо безопасно использует собственный unpaired `ACCEPTED COMPLETE` того же actor/session/step/entity и связывает единственный `QualityDecision`. Event, projection, решение, rework status и audit фиксируются одним commit. Код операции произвольный: сервер не ищет подстроку `QC`. `allows_rework=false` не запрещает первичный контроль, но запрещает reinspection.

Success POST и status имеют общую форму:

```json
{
  "inspection_id": "uuid",
  "status": "ACCEPTED",
  "accepted": true,
  "terminal": true,
  "retryable": false,
  "duplicate": false,
  "server_received_at": "2026-10-25T06:01:00+00:00",
  "message": "Проверка ОТК сохранена сервером",
  "inspection": {
    "event_id": "uuid",
    "decision_id": "uuid",
    "subject_qr": "DEMO-WIP-004",
    "decision": "REJECT",
    "defect_code": "DEMO-ASSEMBLY",
    "defect_label": "ДЕМО · сборка",
    "attempt_type": "PRIMARY",
    "mode": "FIRST_PASS",
    "corrected": false,
    "display_status": "ACCEPTED",
    "row": {"id": "uuid", "code": "DEMO-QC-01", "name": "ОТК"},
    "route_step": {"id": "uuid", "code": "DEMO-QC", "name": "Первичный контроль ОТК"},
    "server_received_at": "2026-10-25T06:01:00+00:00",
    "created_at": "2026-10-25T06:01:00+00:00"
  }
}
```

Первый POST возвращает `duplicate=false`, безопасный повтор того же UUID/actor/canonical body — исходный результат с `duplicate=true`. Изменённое body даёт `409 QC_INSPECTION_PAYLOAD_MISMATCH`, другой actor — `403 QC_INSPECTION_OWNER_MISMATCH`; оба ответа non-terminal для существующего pending, чтобы клиент не очистил чужую или изменённую команду. После concurrent unique conflict сервер повторно читает decision и receipt: совпавший UUID/actor/hash возвращается как duplicate success; определённый semantic duplicate другого UUID отклоняется, неопределённый конфликт остаётся retryable.

Domain 4xx после гарантированного rollback возвращает `submission={inspection_id,status:"REJECTED_TERMINAL",accepted:false,terminal:true,retryable:false,next_steps:["FIX_AND_RESCAN"]}` рядом с `error`. `401`, `5xx`, owner/payload mismatch, неопределённая конкуренция и `GET status → NOT_FOUND` не являются terminal acknowledgement; клиент хранит body и повторяет тот же UUID. Valid pending нельзя отменить по одному `NOT_FOUND`: это создало бы race с in-flight POST. Повреждённый local JSON разрешает foreman/admin через существующий аудируемый `/operation-events/resolve-local-corruption`; это подтверждение локальной коррупции, а не отмена server request.

`decision=REJECT` требует code из `GET /qc-defect-reasons`; `ACCEPT` требует `defect_code=null`. Демо-envelope: `{"items":[{"code":"DEMO-JOINT","label":"ДЕМО · соединение или пайка"},{"code":"DEMO-ASSEMBLY","label":"ДЕМО · сборка"},{"code":"DEMO-COMPONENT","label":"ДЕМО · компонент"},{"code":"DEMO-OTHER","label":"ДЕМО · другое"}],"synthetic":true}`. Это учебный справочник, не заводские нормы.

Attempt/mode определяет только сервер. `FIRST_PASS` использует `PRIMARY`. После отдельного явного rework order и производственной переделки состояние `READY_FOR_QC` создаёт `REINSPECTION/REWORK`; attempt number равен `max` всех сохранённых COMPLETE этого entity+control step плюс один. После решения order становится `REINSPECTED` независимо от ACCEPT/REJECT: это значит «цикл повторно проверен», а не «годен». Повторный REJECT требует нового явного rework order по последнему effective reject; старый reject и второй active order отклоняются. Finalize опирается на последнее effective решение, поэтому ранний ACCEPT не маскирует поздний REJECT.

`GET /me/qc-shift-activity?limit=10` возвращает:

```json
{
  "shift": {"id": "uuid", "code": "DEMO-SHIFT-2026-10-25-D", "production_date": "2026-10-25"},
  "context": {"work_session_id": "uuid", "row": {}, "route_step": {}},
  "checked_count": 4,
  "accepted_count": 2,
  "rejected_count": 2,
  "first_pass_count": 4,
  "reinspection_count": 0,
  "recent_inspections": [],
  "note": "Найденный брак считается выполненной проверкой ОТК; это не персональный KPI контролёра."
}
```

Counts используют только effective decisions текущего actor в активной смене, чьи linked events `ACCEPTED + COMPLETE` и не погашены accepted correction. Reject остаётся выполненной проверкой и не является штрафом контролёру. Recent10 хранится newest-first по server decision `created_at`, включает исправленные исторические решения с `corrected=true`, `display_status="CORRECTED"`; такое решение не входит в effective counts, не показывается зелёным и не предлагается как основание rework. Каждый recent item содержит тот же inspection payload плюс `inspection_id`.

Новая route version создаётся как `DRAFT`, проверяет непрерывную последовательность, уникальные code/sequence и scope рядов, затем отдельно публикуется и становится неизменяемой. Текущая P0-модель умеет один точный ряд или полный набор трёх альтернативных сборочных рядов; произвольное подмножество альтернатив требует отдельной mapping-модели и поэтому отклоняется явно.

Route create: `{model_id,steps:[{code,name,sequence,entity_type:"COMPONENT"|"WIP",allowed_row_ids,allows_rework}]}`. Несколько allowed rows допустимы только как полный набор трёх ASSEMBLY-рядов; имя операции произвольное. Entity create: `{qr_code,entity_type:"COMPONENT"|"WIP"|"FINAL",route_version_id,final_serial?}`; опубликованный маршрут, QR и final serial проверяются сервером. Для FINAL без `final_serial` используется QR. Branch graph и частичное подмножество альтернатив остаются вне P0.

## Расчёт и snapshot

Calculation разделяет `approval_status` и `maturity_state`; содержит `reason_flags`, `a_plan`, `a_volume`, `p`, `q`, `kpi_raw`, nullable `kpi_official`, отдельный объект `otk`, `inputs`, `trace` и `version`.

`GET /dashboard` дополнительно возвращает `row_metrics` для всех пяти рядов и тот же объект в `rows[i].metrics`: `a_plan`, `a_volume`, `p`, `h_accounted_hours`, `q`, `kpi_raw`, `kpi_official`, `reason_flags`, `inputs`, `trace`. Для сборки/пайки качество нельзя честно атрибутировать к ряду, поэтому `q` и KPI равны `null` с `ROW_QUALITY_NOT_ATTRIBUTABLE`; A/P/H остаются вычисленными. Для единственного ряда ОТК `q` — отдельный `q_decision` независимого аудита.

`trace` фиксирует фактически применённые версии плана, норм и методики. Нормы строк утверждённого плана являются snapshot в человеко-минутах; новая версия норм не меняет уже утверждённый отчёт. `POST /approve` создаёт уникальный snapshot `(shift_id, shift_version)` и журнал аудита. CSV строится из того же snapshot.

`POST /plans` и `POST /standards` по умолчанию работают как `mode: "PATCH"`: новая версия клонирует последнюю и заменяет только присланные ключи, поэтому форма одной строки не удаляет остальные позиции. `mode: "FULL"` требует `confirm_full_replacement: true`. Плановые нормы всегда копируются из закреплённой approved standard version, а не доверяются браузеру.

Новое назначение, пересекающее активное назначение сотрудника, получает `409 ASSIGNMENT_OVERLAP`. Перевод выполняется тем же POST с `transfer_from_assignment_id`: сервер атомарно завершает прежний интервал в момент начала нового и пишет audit event. Учтённые часы остаются отдельным ledger и не выводятся из интервалов/сканов.

## Границы DEMO

- `SQLite` — переносимый адаптер для локального портфолио; целевой заводской движок — PostgreSQL.
- Нет MES/1С, аппаратной идентификации USB/HID, накопительной offline-очереди, SSO и промышленного HA.
- Демо-методика и нормы синтетические; цифры нельзя использовать как оценку реального завода.
- Переход к пилоту требует discovery, утверждения норм/маршрутов, проверки сети/сканеров, нагрузочного и restore-теста PostgreSQL.
