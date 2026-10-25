import { AlertTriangle, ArrowRight, CalendarDays, ClipboardCheck, Clock3, FileClock, GitBranch, QrCode, RefreshCw, ScrollText } from "lucide-react";
import { useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Bootstrap, Dashboard } from "../api/types";
import { useAuth } from "../app/AuthContext";
import { canAccess, type UiArea } from "../app/capabilities";
import { formatDate, formatDateTime, formatDecimal, formatRatio, humanize } from "../app/format";
import { useResource } from "../app/useResource";
import { EmptyState, ErrorState, LoadingState } from "../components/PageState";
import { PageHeader, SectionHeader } from "../components/PageHeader";
import { MetricStrip } from "../components/MetricStrip";
import { StatusBadge, toneForStatus } from "../components/StatusBadge";

export function DashboardPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const bootstrap = useResource(() => api.get<Bootstrap>("/bootstrap"), []);
  const canViewReports = Boolean(user?.capabilities.includes("view_reports") || user?.capabilities.includes("admin"));
  const dashboard = useResource(
    () => canViewReports ? api.get<Dashboard>("/dashboard") : Promise.resolve(null as unknown as Dashboard),
    [canViewReports],
  );
  const roles = new Set(user?.roles.map((role) => role.name) ?? []);
  const candidateActions: Array<{ area: UiArea; to: string; title: string; detail: string; icon: typeof QrCode }> = roles.has("FOREMAN") && !roles.has("ADMIN") ? [
    { area: "scan", to: "/scan", title: "Проверить рабочее сканирование", detail: "Разберите неподтверждённую операцию до следующего QR", icon: QrCode },
    { area: "workforce", to: "/workforce", title: "Сверить состав и часы", detail: "Производительность опирается на учёт времени, не на интервалы сканов", icon: Clock3 },
    { area: "configuration", to: "/configuration", title: "Создать WIP или QR изделия", detail: "Опубликованный маршрут используется как неизменяемый контекст", icon: GitBranch },
  ] : roles.has("SUPERVISOR") && !roles.has("ADMIN") ? [
    { area: "reports", to: "/reports", title: "Проверить готовность KPI", detail: "Сверьте расчёт, причины и статус утверждения", icon: ClipboardCheck },
    { area: "audit", to: "/audit", title: "Открыть журнал аудита", detail: "Проследите изменения, авторов и причины", icon: FileClock },
    { area: "entities", to: "/entities", title: "Проверить маршрут изделия", detail: "Найдите QR и просмотрите подтверждённую историю", icon: ScrollText },
  ] : [
    { area: "configuration", to: "/configuration", title: "Проверить маршруты и QR", detail: "Создайте объект или новую версию маршрута", icon: GitBranch },
    { area: "workforce", to: "/workforce", title: "Сверить состав и часы", detail: "Проверьте назначения и учтённый ресурс", icon: Clock3 },
    { area: "reports", to: "/reports", title: "Проверить готовность KPI", detail: "Откройте расчёт, причины и утверждение", icon: ClipboardCheck },
  ];
  const quickActions = user ? candidateActions.filter((action) => canAccess(user, action.area)) : [];

  const metrics = useMemo(() => dashboard.data ? [
    { key: "a_plan", label: "Номенклатурный план", value: dashboard.data.calculation.a_plan, hint: "Входит в КПД" },
    { key: "a_volume", label: "Валовый объём", value: dashboard.data.calculation.a_volume, hint: "Контроль объёма", diagnostic: true },
    { key: "p", label: "Производительность", value: dashboard.data.calculation.p, hint: "Учтённые часы" },
    { key: "q", label: "Качество", value: dashboard.data.calculation.q, hint: "Первое предъявление" },
    {
      key: "kpi",
      label: dashboard.data.calculation.kpi_official === null && dashboard.data.calculation.kpi_raw !== null ? "КПД (расчётный)" : "КПД",
      value: dashboard.data.calculation.kpi_official ?? dashboard.data.calculation.kpi_raw,
      hint: "Итоговый показатель",
      valueIsPercent: true,
      statusLabel: dashboard.data.calculation.kpi_official !== null ? "Утверждённый" : dashboard.data.calculation.kpi_raw !== null ? "Расчётный · не утверждён" : "Нет расчёта",
      statusTone: dashboard.data.calculation.kpi_official !== null ? "success" as const : dashboard.data.calculation.kpi_raw !== null ? "warning" as const : "neutral" as const,
    },
  ] : [], [dashboard.data]);

  if (bootstrap.loading) return <div className="page"><LoadingState rows={8} label="Загружаем рабочую сводку" /></div>;
  if (bootstrap.error) return <div className="page"><ErrorState message={bootstrap.error.message} onRetry={() => void bootstrap.reload()} /></div>;
  if (!bootstrap.data?.active_shift) return <div className="page"><PageHeader title="Сводка смены" /><EmptyState title="Активная смена не назначена" message="Планировщик должен создать смену и назначить состав до начала сканирования." /></div>;

  const { active_shift: shift } = bootstrap.data;
  const rows = dashboard.data?.rows ?? bootstrap.data.rows;
  const reasonFlags = dashboard.data?.calculation.reason_flags.filter((flag) => !flag.startsWith("SYNTHETIC")) ?? [];
  return (
    <div className="page">
      <PageHeader
        title="Сводка смены"
        description={`${shift.code} · ${formatDate(shift.production_date)} · синтетическая смена`}
        meta={<span className="demo-marker">ДЕМО</span>}
        actions={<button className="button button--secondary" type="button" onClick={() => void Promise.all([bootstrap.reload(), dashboard.reload()])}><RefreshCw size={16} />Обновить</button>}
      />

      <section className="context-bar" aria-label="Статусы смены и расчёта">
        <div><span>Смена</span><StatusBadge tone={toneForStatus(shift.approval_status)}>{humanize(shift.approval_status)}</StatusBadge></div>
        <div><span>Готовность KPI</span><StatusBadge tone={toneForStatus(shift.maturity_state)}>{humanize(shift.maturity_state)}</StatusBadge></div>
        <div><span>Обновлено</span><strong>{formatDateTime(bootstrap.data.updated_at)}</strong></div>
      </section>

      <section className="workspace-section">
        <SectionHeader title="КПД и компоненты" description="Закрытие смены и зрелость расчёта показаны независимо. Нажмите компонент, чтобы открыть источники." />
        {!canViewReports ? <EmptyState title="Показатели доступны руководителю" message="Оператор видит свой рабочий контекст; расчёт смены доступен ролям отчётности." /> : dashboard.loading ? <LoadingState rows={3} /> : dashboard.error ? <ErrorState message={dashboard.error.message} onRetry={() => void dashboard.reload()} /> : dashboard.data ? (
          <>
            <MetricStrip items={metrics} onOpen={() => navigate("/reports")} />
            {reasonFlags.length > 0 && <div className="reason-line"><AlertTriangle size={16} /><span>{reasonFlags.map(humanize).join(" · ")}</span></div>}
          </>
        ) : <EmptyState title="Расчёт ещё не создан" message="Нужны подтверждённые события, план, нормы и учтённые часы." />}
      </section>

      <section className="workspace-section">
        <SectionHeader title="Пять рядов" description="Три сборочных ряда — параллельные производственные полосы, не последовательные этапы." />
        <div className="row-board">
          {rows.map((row) => (
            <article className="production-row" key={row.id} data-kind={row.category.toLowerCase()}>
              <div className="production-row__identity"><span className="row-symbol" aria-hidden="true">{row.category === "ASSEMBLY" ? "С" : row.category === "SOLDER" ? "П" : "О"}</span><div><h3>{row.name}</h3><p>{row.code}</p></div></div>
              <div className="production-row__facts"><span><strong>{row.accepted_operations ?? "—"}</strong> принятых операций</span></div>
              <div className="production-row__metrics" aria-label={`Показатели ${row.name}`}>
                <span><small>План</small><strong>{formatRatio(row.metrics?.a_plan)}</strong></span>
                <span><small>Производит.</small><strong>{formatRatio(row.metrics?.p)}</strong></span>
                <span title={row.metrics?.reason_flags.map(humanize).join(" · ")}><small>Качество</small><strong>{formatRatio(row.metrics?.q)}</strong></span>
                <span><small>КПД</small><strong>{row.metrics?.kpi_official === null || row.metrics?.kpi_official === undefined ? "—" : `${formatDecimal(row.metrics.kpi_official, 1)} %`}</strong></span>
              </div>
              <StatusBadge tone="neutral">{humanize(row.category)}</StatusBadge>
            </article>
          ))}
        </div>
      </section>

      <section className="dashboard-lower">
        <div className="workspace-section attention-queue">
          <SectionHeader title="Следующие действия" description="Сначала блокировки и неполные данные, затем аналитика." />
          <div className="action-list">
            {quickActions.map((action) => {
              const Icon = action.icon;
              return <Link key={action.to} to={action.to}><span className="action-icon"><Icon /></span><span><strong>{action.title}</strong><small>{action.detail}</small></span><ArrowRight /></Link>;
            })}
          </div>
        </div>
        <aside className="workspace-section shift-facts">
          <SectionHeader title="Контекст" />
          <dl><div><dt><CalendarDays />Производственная дата</dt><dd>{formatDate(shift.production_date)}</dd></div><div><dt><QrCode />Версия данных</dt><dd>{bootstrap.data.version}</dd></div><div><dt>Режим</dt><dd>Синтетические данные</dd></div></dl>
        </aside>
      </section>
    </div>
  );
}

