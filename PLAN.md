# План проекта: КПД производства квадрокоптеров

Статус: P0-Demo в активной разработке по явному разрешению пользователя от 25 октября 2026 года. Дата актуализации: 25 октября 2026 года.

Создан рабочий backend demo, расчётное ядро, миграции, синтетический seed, тесты и frontend; это не означает готовность к заводскому пилоту. Реальные данные, нормы и промышленная эксплуатация по-прежнему требуют discovery и отдельных gates.

Фактически проверено на текущей машине: Python 3.12 `.venv`, persistent SQLite DEMO fallback, 76 backend tests, Alembic migration+seed, cookie auth/RBAC/CSRF, QR scan/dedupe/route validation, серверные личные итоги worker/QC и server-scoped итог одного ряда для FOREMAN, атомарная проверка ОТК, настраиваемые route/entity, genealogy, roster/time ledger, КПД пяти рядов, ОТК/rework/audit, plan/standard PATCH versions, approval snapshot/CSV, restart persistence и SQLite backup/restore. PostgreSQL/Docker здесь отсутствуют и ещё не проверены; порт 8000 занят чужим приложением, поэтому demo API использует `127.0.0.1:8010`.

## 1. Назначение и источники детализации

Этот файл — самодостаточная точка входа: контекст, P0/P1, методика-кандидат, архитектура, зависимости, оценки, критерии готовности и discovery.

Подробности находятся в:

- `docs/01-product-and-metrics.md` — предметная модель, показатели, ОТК и численные примеры;
- `docs/02-architecture-and-delivery.md` — архитектура, безопасность, инфраструктура и поставка;
- `docs/03-ux-quality-and-portfolio.md` — UX, QA, доступность и портфолио;
- `TEAM.md`, `AGENTS.md`, `team/*.md` — команда, правила и устойчивая память.

При расхождении действует последнее явное указание пользователя, затем этот план, затем профильная детализация.

## 2. Подтверждённый контекст

- Продукция — квадрокоптеры; задача — производственный учёт и расчёт КПД.
- Первый контур — одна заводская площадка и одна пилотная модель.
- На участке пять рядов: три сборочных, один пайки, один ОТК.
- На каждом ряду есть бригадир.
- Состав работников меняется ежедневно и может меняться внутри смены.
- У каждого работника отдельный компьютер или планшет со сканером.
- У деталей собственные QR; финальный QR/serial готового квадрокоптера появляется позднее.
- Предлагается временный QR сборочной единицы/WIP; его момент создания подтверждается на discovery.
- Маршруты настраиваемые и версионируемые.
- Три сборочных ряда нельзя заранее считать обязательной последовательностью: возможны параллельные, альтернативные или разные операции.
- Пилот должен охватить все реально применимые к одной модели ряды и все P0-роли.
- Реальные нормы существуют, но пока не предоставлены; численные цели не выдумываются.

## 3. Цель и проверяемый эффект

Планируется многопользовательское веб-приложение, связывающее roster, QR-события операций, маршрут, genealogy, труд, качество, ОТК, утверждение и отчёт.

Основной поток: `Ввод данных / QR-скан → Проверка → Расчёт → Отчёт`.

Система должна отвечать:

1. Кто, где, в какой смене и над каким объектом заявил завершение операции?
2. Допустима ли операция для entity type и версии маршрута?
3. Не является ли событие дублем, пропуском или неразрешённой попыткой?
4. Какие детали связаны с WIP и финальным изделием и как менялись связи?
5. Покрыт ли план по каждой фиксированной позиции, а не только общий объём?
6. Какова отдача фактически учтённого трудового ресурса?
7. Какая зрелая когорта прошла первое предъявление?
8. Насколько корректны решения ОТК по независимому аудиту?
9. Из каких событий, часов, норм и версий получено каждое число?

До пилота эффект — гипотеза. На discovery фиксируется baseline, затем сравниваются сопоставимые периоды и scope.

Измерять можно время закрытия смены, полноту genealogy, долю объяснимых расчётов, число остановленных дублей, ручные исправления, scan latency, охват ОТК, размеры audit sample и успешность restore drill.

Цели и допустимые отклонения утверждает завод. Нельзя обещать рост КПД, экономию или снижение брака без замеров.

## 4. P0-Demo, P0-Pilot и P1

### P0-Demo

Демо использует только детерминированные синтетические данные и включает:

- одну модель, пять рядов, основные роли и версионируемый маршрут;
- roster, переводы, QR primary/rework/control/correction events;
- component → WIP → final genealogy, replacement и scrap history;
- idempotency, semantic duplicate, route exceptions и один pending scan;
- synthetic нормы/часы с постоянной маркировкой `ДЕМО`;
- производственный расчёт-кандидат и отдельную оценку ОТК;
- версии, approval, maturity, audit trail и воспроизводимый отчёт;
- README, ADR, тестовый отчёт и короткое видео.

Демо не доказывает готовность к эксплуатации.

### P0-Pilot

Пилот добавляет реальный согласованный маршрут одной модели, реальные типы компьютеров/сканеров, реальные роли, утверждённые нормы/план/часы/методику, независимую перепроверку ОТК, локальное развёртывание, TLS, backup/restore, мониторинг, обучение и параллельный прогон.

Общий ROM `96–159 человеко-дней` включает discovery, P0-Demo, подготовку и проведение P0-Pilot, документацию и портфолио.

ROM не включает закупку оборудования, ожидание доступов/согласований, большую очистку истории и промышленный rollout после пилота.

### P1 после успешного пилота

- дополнительные модели, маршруты, площадки и цеха;
- изученные и согласованные интеграции MES/1С/ERP/СКУД;
- полноценная offline-очередь с конфликтами и защищённой синхронизацией;
- ручной аварийный контур экземплярных событий, если он действительно нужен;
- партийные genealogy-события `split/merge`;
- высокая доступность и автоматический failover;
- расширенная статистика качества и аналитика баланса рядов.

P1 не входит в текущую оценку.

## 5. Роли и RBAC

| Роль | Основной сценарий | Ограничение |
|---|---|---|
| Работник сборки/пайки | Сканировать завершение назначенной операции | Не меняет route, нормы, часы и чужие события |
| Контролёр ОТК | Фиксировать проверку, решение и дефект | Не переписывает производство и не аудирует сам себя |
| Бригадир ряда | Подтверждать состав, разбирать исключения, открывать разрешённый rework | Только свой scope; решение с причиной |
| Старший ОТК / независимый аудитор | Перепроверять выборку решений | Независимость от исходного решения |
| Планировщик/табельщик | Вести план, roster и учтённые часы | Не меняет QR-факты и решения ОТК |
| Технолог/нормировщик | Вести маршруты, операции, нормы и критерии | Опубликованная версия неизменяема |
| Начальник смены/производства | Проверять и утверждать период | Не утверждает неполный конфликтный набор |
| Аналитик/аудитор | Читать отчёт и происхождение | Только чтение разрешённого scope |
| Администратор | Пользователи, роли, устройства, справочники | Не переписывает закрытый факт |

Роль определяет действие, scope — площадку/ряд/смену/объект. Backend проверяет каждый объект; скрытая кнопка не является защитой. Критические действия используют разделение обязанностей.

## 6. Сценарии MVP

### Подготовить смену

Планировщик создаёт смену и назначения пяти рядов. Бригадиры подтверждают фактический состав и временные изменения. Система выявляет пересечения, отсутствие бригадира, workstation и действующей route/norm version.

### Завершить операцию

UI-сессия связывает `worker + workstation + row + operation + shift`. Сканер не доказывает личность. Работник сканирует QR после операции; скан является заявлением, не физическим доказательством выполнения.

Сервер проверяет assignment, entity type, route version, переход, controlled attempt и duplicate. Авторитетное время — серверное; время устройства диагностическое.

### Потерять ответ безопасно

MVP online-first. До запроса клиент создаёт UUID и сохраняет ровно один durable pending scan. До однозначного ответа новые сканы заблокированы. После связи выполняется status/retry с тем же UUID.

Pending переживает reload и смену пользователя, не меняет автора и разрешается исходным работником после re-auth либо отдельным аудируемым действием бригадира. Полная offline queue вне MVP.

### Разобрать исключение

Технический дубль, допустимый повтор, rework и неверный маршрут различаются. Исходное событие не удаляется; исправление — связанное компенсирующее событие. Новая попытка открывается разрешённым серверным действием.

### Закрыть смену

Бригадиры подтверждают assignments, TIME_ENTRY и исключения. ОТК завершает решения и предусмотренный независимый audit. Сервер проверяет события, genealogy, план, нормы, часы и версии; затем уполномоченная роль утверждает snapshot.

## 7. Модель данных

Основные сущности:

- `Plant`, `OrgUnit`, `ProductionRow`, `Workstation`;
- `Employee`, `User`, `Role`, `UserRoleScope`;
- `Shift`, `ShiftAssignment`, `TimeEntry`;
- `ProductModel`, `TrackedEntity`, QR/serial identifier;
- `RouteVersion`, `RouteStep`, разрешённые transitions/entity types;
- `ProductionPlanVersion`, `PlanLine` с фиксированным scope и количеством;
- append-only `OperationEvent` и пересобираемый `OperationProjection`;
- `GenealogyLink` с attach/detach/replace/scrap/rework/final-link;
- `StandardSetVersion`, `StandardValue`, `MethodologyVersion`;
- `QualityDecision`, `IndependentAuditSample`;
- `ImportBatch`, `ImportRow`, mapping/error;
- `CalculationRun`, `ApprovedResultSnapshot`, `AuditEvent`.

`OperationEvent` содержит event UUID, entity type/id, route/step/attempt, employee/assignment/workstation/row/shift, outcome, server time, device time с trust flag, correction/rework/source links.

Техническая уникальность защищает event UUID. Семантическая — комбинацию `entity + route + operation + attempt + completion kind`.

`ProductionPlanVersion` относится к смене/периоду и после approval неизменяема. `PlanLine` фиксирует model, route step/operation, quantity, норматив и необязательный row. Корректировка создаёт новую plan version с `supersedes`, причиной и повторным approval.

Каждый учитываемый факт сопоставляется максимум одной `PlanLine` выбранной версии: один факт не покрывает две позиции. Calculation snapshot хранит `plan_version_id` и mapping факт→строка; разрешённая замена позиции задаётся правилом версии плана.

Деталь/WIP не увеличивает finished units. Финальный выпуск возникает только при согласованном состоянии `final_product`.

В genealogy MVP входят только сериализованные компоненты/узлы: attach, detach, replace, scrap, rework и WIP→final serial. Одна активная физическая деталь не принадлежит двум изделиям. Партийные split/merge — P1.

`TimeEntry` хранит категорию `primary/rework/waiting/setup/support/unavailable`, интервал или часы, источник, approval, version и correction/supersedes. `H_accounted` строится из ledger; межскановые интервалы его не меняют.

Approval смены и зрелость показателя — разные оси: `approval_status`, `maturity_state=PROVISIONAL/AWAITING_AUDIT/FINAL`, reason flags `INCOMPLETE_DATA/QUALITY_GATE_FAILED/...`.

## 8. Методика производственного КПД

Формулы ниже — кандидат для согласования, не заводской регламент. `s_i` — норматив строки в человеко-минутах; деление на 60 переводит результат в нормо-часы.

```text
E_fact = Σ[q_fact_i × s_i] / 60
E_plan = Σ[q_plan_i × s_i] / 60
E_plan_covered = Σ[min(q_fact_i, q_plan_i) × s_i] / 60
A_volume = E_fact / E_plan
A_plan = E_plan_covered / E_plan
```

`i` — фиксированная строка версии плана: модель, операция и при необходимости ряд/задание. `A_volume` показывает сырой объём и может быть выше 100%. `A_plan` находится в 0–100% и не позволяет сверхплану одной строки закрыть дефицит другой. Composite использует только `A_plan`.

Rework не создаёт второй earned output. Согласованная замена плановой позиции возможна только правилом версии плана.

```text
H_accounted = фактически потреблённые человеко-часы по версии методики
P_raw = E_fact / (H_accounted × ρ_target)
```

`H_accounted` берётся из TIME_ENTRY/табеля, включает rework и другие утверждённые потреблённые категории. Для коллективной операции применяются человеко-минуты. Межскановый интервал не является трудовым временем.

```text
E_quality_eligible = нормо-часы созревшей когорты, подлежащей оценке
E_first_pass_good = её нормо-часы, принятые с первого предъявления
Q_fpy = E_first_pass_good / E_quality_eligible
O = min(A_plan, P_raw, 1)
KPI_raw = 100% × O × Q_fpy
```

`KPI_official` возможен только при полноте данных, `maturity_state=FINAL`, пройденном `Q_min` и отсутствии critical quality hold. Завод утверждает `ρ_target`, `Q_min`, состав `H_accounted`, окно созревания, rounding и exclusions.

Отсутствующий знаменатель даёт `NULL` и reason code, а не 0. Группы считаются отношением сумм однородных числителей и знаменателей; `E_plan_covered` сначала считается внутри каждой исходной строки. Среднее процентов запрещено.

## 9. Отдельная оценка ОТК

Найденный инспектором дефект характеризует входящее качество, а не плохую работу контролёра. Производственный `Q_fpy` не является KPI ОТК.

```text
Coverage = inspected_due / inspection_due
Timeliness = decisions_within_SLA / decisions_due
Confirmed_escape_rate = confirmed_missed_defects / independently_audited_accepts
Confirmed_false_reject_rate = overturned_rejects / independently_audited_rejects
```

Кандидат отдельного composite:

```text
s_otk_i = норматив контрольной операции, человеко-минуты
E_otk_fact = Σ[fact_i × s_otk_i] / 60, НЧ
E_otk_plan = Σ[plan_i × s_otk_i] / 60, НЧ
E_otk_plan_covered = Σ[min(fact_i, plan_i) × s_otk_i] / 60, НЧ
A_otk_plan = E_otk_plan_covered / E_otk_plan
P_otk = E_otk_fact / (H_otk_accounted × ρ_otk_target)
O_otk = min(A_otk_plan, P_otk, 1)
KPI_otk_raw = 100% × O_otk × Q_decision
```

`Q_decision` получается только из независимого корректного аудита. При сопоставимой случайной выборке допустимо `correct_audited/all_audited`; при известной стратифицированной — утверждённая взвешенная оценка; при неизвестной/смещённой выборке `Q_decision=NULL` и composite ОТК `NULL`.

Отсутствие рекламаций или аудита не равно 100%. Состояния: `PROVISIONAL → AWAITING_AUDIT → FINAL`.

## 10. Блокеры официальной методики

До official KPI необходимо:

- обследовать операции пяти рядов и физический объект пайки;
- подтвердить WIP QR, final serial и правила genealogy;
- определить фиксированные строки плана и допустимые замены;
- получить нормы пилотной модели и правила их действия;
- согласовать источник/категории `H_accounted`;
- согласовать `ρ_target`, `Q_min`, quality hold, maturity window и rounding;
- утвердить независимый sampling/audit protocol ОТК;
- подписать golden examples и владельцев закрытия/пересчёта.

Опубликованные route, norm и methodology version неизменяемы. Исправление создаёт новую версию. Закрытый snapshot хранит входной hash, события, версии, компоненты и округление. Новая норма не меняет историю молча.

## 11. Архитектура и стек

Стиль — модульный монолит: один backend deployable, один frontend и PostgreSQL.

Рекомендуемый стек:

- поддерживаемая совместимая версия Python, FastAPI, Pydantic;
- стабильные SQLAlchemy и Alembic;
- поддерживаемая стабильная PostgreSQL;
- React, TypeScript strict и Vite;
- OpenAPI как источник TypeScript-контракта;
- pytest, component tests и Playwright;
- OCI containers, Docker Compose, локальный Linux server/VM и TLS reverse proxy;
- JSON logs, Prometheus metrics и согласованный dashboard/alerting.

Точные версии выбираются compatibility spike и фиксируются lock-файлами/image digest. Kafka, микросервисы и Kubernetes исходному масштабу не нужны.

Backend выполняет авторитетные расчёты. Нормативная математика использует Decimal/PostgreSQL `numeric`, промежуточные значения не округляются.

## 12. Конкурентность, импорт и инфраструктура

Черновики используют optimistic concurrency и version/`If-Match`; last-write-wins запрещён.

Утверждение смены одной транзакцией блокирует shift, фиксирует верхнюю границу event journal, проверяет pending/exceptions/genealogy/time ledger, выбирает versions, рассчитывает snapshot, записывает approval и audit. Approval не переводит незрелый KPI в `FINAL`.

Переоткрытие требует права, причины, компенсирующих событий и новой ревизии.

MVP не обещает автоматическую MES/1С/ERP/СКУД-интеграцию. CSV/XLSX для плана, норм, roster/часов и справочников проходит `upload → staging → validation → preview → apply` и является идемпотентным. Ручной сменный/партийный агрегат не заменяет QR-события.

Рабочий контур не зависит от интернета. Предпочтителен заводской OIDC/IdP; автономный пилот использует серверную сессию, Argon2id, `HttpOnly/Secure/SameSite` cookie, CSRF и отзыв. Secrets не входят в Git/images.

Backup хранится отдельно и считается рабочим после restore drill. При строгом RPO проектируется WAL/PITR. Single-node Compose не объявляется HA.

## 13. UX и качество

Основные экраны: вход, сводка пяти рядов, roster, scan screen, лента route/genealogy, exceptions, rework, shift close, calculation drill-down, reports, methodology и audit.

Worker scan screen использует компактную шапку и показывает крупное поле QR, смену, ряд, операцию, серверное число первичных операций за смену, rework отдельно и последние 10 сканов. Рабочее место доступно в деталях; demo QR, UUID и технические коды ответа из обычного worker-вида убраны. Pending/retry с тем же UUID и однозначные статусы «Принято / Нужна проверка / Не принято / Не подтверждено сервером» сохранены.

QC workspace использует такую же компактную оболочку: крупный QR, «Годен»/«Брак», обязательную серверную DEMO-причину брака, личное число проверок, повторный контроль отдельно и последние 10 решений. QR-событие и решение сохраняются атомарно; один общий pending-инвариант блокирует параллельные worker/QC действия, а rework остаётся отдельным явным шагом.

FOREMAN workspace `/foreman` показывает только один серверно определённый ряд: состав назначений, effective primary/rework за смену, последние сохранённые проблемы сканирования и переделки с подтверждённой привязкой. Глобальные dashboard/routes/plans/audit и другие прежние разделы для demo-бригадира скрыты и защищены на уровне UI route; это не заявляется как полный редизайн backend RBAC.

Статус выражается текстом и формой, не только цветом. Ошибка не очищает ввод и не показывает ложное «сохранено».

Цель после реализации — WCAG 2.2 AA: keyboard, visible focus, reflow 200%, contrast, screen reader и табличная альтернатива графикам. Соответствие не заявляется до проверки.

25 октября 2026 года для P0-Demo зафиксирована ролево-релевантная навигация: меню, стартовый экран и защита прямых UI URL задаются ролью вместе с выданными backend capabilities; закрытая страница не монтируется и не запрашивает свои данные. Матрица и граница между demo-UX и заводским регламентом описаны в `docs/03-ux-quality-and-portfolio.md`.

## 14. Дорожная карта: шесть этапов

Один человеко-день — 6–7 часов сфокусированной работы. AI не ускоряет физические согласования, доступы, UAT и наблюдение пилота.

| Этап | Зависимости и объём | Критерий выхода | ROM |
|---|---|---|---:|
| **1. Методика** | Discovery пяти рядов, QR/WIP/final, routes/rework, plan/norm/hour sources, A_plan, quality cohorts, ОТК audit, scanner/network, NFR | Подписаны словарь, P0, formula/genealogy golden examples, audit protocol, pilot criteria; вопросы имеют владельцев | 16–25 |
| **2. Основа системы** | Compatibility spikes, ADR/threat model, CI/migrations, OpenAPI, auth/RBAC, оргструктура, workstations, entity/route skeleton, telemetry | Подтверждены совместимость, схема, доступ и deploy plan; версии готовы к lock | 17–27 |
| **3. Учёт смен** | Roster/assignments, TIME_ENTRY, scan session, event journal, pending UUID, projections, serial genealogy, replacement, ОТК/rework, imports | Дубль/route/bind блокируется; pending не теряет автора; часы не выводятся из сканов; projection rebuild совпадает | 23–38 |
| **4. Расчёт КПД** | Versioned A_volume/A_plan, H_accounted, E_quality_eligible, independent OTK audit, Decimal, approval/maturity/reasons, snapshots | Golden tests совпадают; surplus не скрывает deficit; biased OTK sample даёт NULL; history воспроизводима | 14–23 |
| **5. Отчёты** | Ввод→проверка→расчёт→отчёт, dashboard, drill-down, export, audit viewer, accessibility | Каждое число объяснимо; snapshot/export совпадают; scope соблюдён; критические пути доступны | 8–14 |
| **6. Пилот** | TLS/secrets, restore, monitoring, security/performance, реальные scanners, обучение, parallel run, portfolio | Restore/alerts/UAT выполнены; смены сверены; принято отдельное go/no-go; demo запускается без реальных данных | 18–32 плюс календарное наблюдение |

Итого: **96–159 человеко-дней**, до discovery ориентировочная точность −25%/+50%. После этапа 1 backlog и оценки пересчитываются.

## 15. Критерии готовности P0

- Утверждены route, norms, plan lines, `H_accounted`, `E_quality_eligible` и independent OTK audit.
- Все пять рядов и P0-роли присутствуют в RBAC и сценариях.
- Retry одного UUID создаёт один факт; новые сканы невозможны при pending.
- Component/WIP/final не смешиваются; active component не связан с двумя изделиями.
- Replacement, scrap и rework сохраняют историю; split/merge отсутствуют в P0.
- A_plan не позволяет surplus одной строки закрыть deficit другой.
- Основная P использует TIME_ENTRY/H_accounted, включая утверждённый rework.
- Производственный Q использует зрелый `E_quality_eligible`.
- ОТК использует независимый `Q_decision`, а biased/no audit даёт `NULL`.
- Approval и maturity независимы; missing/immature denominator имеет reason code.
- Закрытый отчёт воспроизводится; новая norm version не меняет его молча.
- API/direct link/export проходят RBAC/IDOR; audit отвечает «кто, что, когда, почему».
- Backup восстановлен в изолированный контур; alerts и реальные scanners проверены.
- Основные пути проверены keyboard/screen reader/reflow по согласованной матрице.
- Параллельный прогон завершён и есть подписанное go/no-go; production не подразумевается автоматически.

## 16. Тестовая стратегия

- Unit/property: Decimal, нули, rounding, versions, A_plan line caps, aggregation invariants.
- Golden: утверждённые production и OTK examples.
- Contract: OpenAPI и generated TypeScript client.
- DB: constraints, migrations, locks, active genealogy uniqueness, TIME_ENTRY versions.
- Event/projection: idempotency, duplicate, correction, rework и full rebuild.
- Concurrency: simultaneous scan/bind/approval, retry и rollback.
- Method state: approval не меняет maturity; reason flags блокируют official KPI.
- Import: locale, duplicate, damaged/large CSV/XLSX и supersedes.
- E2E: roster → scan → route/genealogy → ОТК/rework/audit → approval → report.
- Security/accessibility/performance/recovery: по согласованным NFR и реальному оборудованию.

## 17. Риски и discovery

Главные риски: отсутствие норм, неизвестный route, отсутствие WIP QR, нестабильная сеть, слабый источник часов, смещённый audit ОТК, scope creep интеграций, принятие пользователями, single-node failure и утечка данных.

Обязательные вопросы:

1. Какие операции выполняет каждый ряд и как связаны три сборочных ряда?
2. Какой объект проходит пайку и какой QR он имеет?
3. Когда создаются WIP QR и final serial?
4. Какие attach/detach/replace/scrap/rework допустимы и кто их подтверждает?
5. Что означает completion scan для каждой операции?
6. Какие scanner/OS/browser и насколько надёжна сеть?
7. Где хранится план, какова идентичность строки и какие замены допустимы?
8. Где табель и какие категории входят в `H_accounted`?
9. Какие нормы, `ρ_target`, `Q_min`, rounding и сроки действия утверждены?
10. Что входит в `E_quality_eligible` и когда созревает когорта?
11. Как формируется независимая выборка ОТК и минимум данных?
12. Кто утверждает route/norm/roster/hours/rework/shift и переоткрывает период?
13. Есть ли OIDC/PKI/SIEM/registry/backup platform?
14. Каковы volumes, retention, p95, SLA, RPO/RTO и персональные данные?
15. Как измеряется успех пилота и кто владелец эксплуатации после него?

## 18. Портфолио-демо

Минимальный synthetic set: корректный маршрут, duplicate, перевод работника, bind/replacement, пропущенная пайка, ОТК→rework, independent audit, missing norm, pending retry и новая норма без изменения старого snapshot.

Фактическое портфолио-видео `docs/assets/portfolio-demo.webm` длительностью `4:09,7` показывает живой browser flow: создание синтетического WIP, пайку, сборку, server acknowledgement, атомарный брак ОТК, отдельную переделку, явный REWORK, повторный контроль, отчёт и scoped экран бригадира. Расширенные genealogy replacement, независимый audit и историческая смена нормы остаются в UI/тестах и не выдаются за показанные в этой короткой записи. Сценарий и проверка: `docs/portfolio-demo-script.md`.

Первые четыре пункта локальной подготовки портфолио завершены: обзорный `README.md`, краткий `docs/portfolio-case.md`, проверенное видео со сценарием и подготовленный `.github/workflows/ci.yml`. В свежей изолированной локальной копии подтверждены backend `76 passed`, frontend `npm ci/typecheck/build PASS` и Playwright `16 passed / 12 intentional skips / 0 failed` на мигрированной и заново засеянной SQLite. GitHub remote не подключён, публикация и hosted Actions run не выполнялись; это завершение упаковки P0-Demo, а не готовность к публичному недоверенному доступу или заводскому пилоту.

Все данные и QR помечены `ДЕМО`; реальные люди, serial, дефекты, нормы и secrets не публикуются.

Существующий плановый визуальный артефакт: `docs/assets/kpd-production-quadcopters.png`. Он не доказывает реализацию или пользовательское тестирование.

## 19. Официальные источники

- [FastAPI: OpenAPI, JSON Schema и security schemes](https://fastapi.tiangolo.com/features/).
- [SQLAlchemy](https://docs.sqlalchemy.org/en/latest/) и [Alembic](https://alembic.sqlalchemy.org/en/latest/).
- [PostgreSQL: isolation](https://www.postgresql.org/docs/current/transaction-iso.html), [backup/PITR](https://www.postgresql.org/docs/current/continuous-archiving.html), [date/time](https://www.postgresql.org/docs/current/datatype-datetime.html).
- [React + TypeScript](https://react.dev/learn/typescript), [TypeScript Handbook](https://www.typescriptlang.org/docs/handbook/intro), [Vite](https://vite.dev/guide/).
- [Docker Compose production](https://docs.docker.com/compose/how-tos/production/) и [Prometheus](https://prometheus.io/docs/introduction/overview/).
- [OWASP Password Storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html) и [Session Management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html).
- [ISO 22400-2](https://www.iso.org/obp/ui/#iso:std:54497:en), [NIST conformity decisions](https://www.nist.gov/publications/assessment-conformity-decision-rules-and-risk-analysis), [GS1 specifications](https://ref.gs1.org/standards/genspecs/), [WCAG 2.2](https://www.w3.org/TR/WCAG22/).

Источники подтверждают технологии и узкие определения, но не утверждают внутреннюю формулу завода.

## 20. Следующий разрешённый шаг

Разработка P0-Demo разрешена и выполняется. Configurable routes/entities, row-level KPI пяти рядов, воспроизводимый lifecycle и основной live frontend E2E уже завершены. Текущая приёмка охватывает упрощённые worker/QC/FOREMAN рабочие экраны, серверные личные/рядовые итоги, атомарное решение ОТК и общий durable pending; далее исправляются только найденные дефекты P0-Demo и фиксируются известные ограничения.

После этого scope не расширяется автоматически: исправляются только найденные дефекты P0-Demo. Переход к реальному P0-Pilot требует отдельного discovery и подтверждения маршрутов, QR, норм, ролей, сети/сканеров, PostgreSQL, ИБ, backup/restore и критериев пилота. Синтетический demo нельзя объявлять промышленно готовым или использовать как доказательство эффекта.

