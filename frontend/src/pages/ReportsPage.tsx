import { CheckCircle2, Download, RefreshCw, ShieldAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { ListResponse, Report, Shift } from "../api/types";
import { useAuth } from "../app/AuthContext";
import { canAccess } from "../app/capabilities";
import { formatDate, formatDateTime, humanize } from "../app/format";
import { useResource } from "../app/useResource";
import { AccessDenied } from "../components/AccessDenied";
import { EmptyState, ErrorState, LoadingState } from "../components/PageState";
import { PageHeader, SectionHeader } from "../components/PageHeader";
import { MetricStrip } from "../components/MetricStrip";
import { StatusBadge, toneForStatus } from "../components/StatusBadge";

export function ReportsPage() {
  const { user } = useAuth();
  const shifts = useResource(() => api.get<ListResponse<Shift>>("/shifts"), []);
  const [shiftId, setShiftId] = useState("");
  const report = useResource(() => shiftId ? api.get<Report>(`/reports/${shiftId}`) : Promise.resolve(null as unknown as Report), [shiftId]);
  const [approving, setApproving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { if (!shiftId && shifts.data?.items[0]) setShiftId(shifts.data.items[0].id); }, [shiftId, shifts.data]);
  if (!user || !canAccess(user, "reports")) return <AccessDenied />;
  const canApprove = canAccess(user, "approve");

  const metrics = useMemo(() => report.data ? [
    { key: "a_plan", label: "Номенклатурный план", value: report.data.calculation.a_plan, hint: "A_plan · входит в КПД" },
    { key: "a_volume", label: "Валовый объём", value: report.data.calculation.a_volume, hint: "A_volume · диагностический", diagnostic: true },
    { key: "p", label: "Производительность", value: report.data.calculation.p, hint: "P · H_accounted" },
    { key: "q", label: "Качество", value: report.data.calculation.q, hint: "Q · первое предъявление" },
    { key: "kpi", label: report.data.calculation.kpi_official === null && report.data.calculation.kpi_raw !== null ? "КПД (расчётный)" : "КПД", value: report.data.calculation.kpi_official ?? report.data.calculation.kpi_raw, hint: "Итоговый показатель", valueIsPercent: true, statusLabel: report.data.calculation.kpi_official !== null ? "Утверждённый" : report.data.calculation.kpi_raw !== null ? "Расчётный · не утверждён" : "Нет расчёта", statusTone: report.data.calculation.kpi_official !== null ? "success" as const : report.data.calculation.kpi_raw !== null ? "warning" as const : "neutral" as const },
  ] : [], [report.data]);

  async function approve() {
    if (!shiftId) return;
    setApproving(true); setMessage(null); setError(null);
    try { await api.post(`/shifts/${shiftId}/approve`); setMessage("Смена утверждена. Готовность KPI остаётся отдельным состоянием."); await report.reload(); await shifts.reload(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Не удалось утвердить смену"); }
    finally { setApproving(false); }
  }

  return <div className="page">
    <PageHeader title="Отчёты и утверждение" description="Все показатели рассчитаны backend и раскрываются до входов, формулы и версии." meta={<span className="demo-marker">ДЕМО</span>} actions={<><button className="button button--secondary" type="button" disabled={!shiftId} onClick={() => void report.reload()}><RefreshCw />Обновить</button><button className="button button--secondary" type="button" disabled={!shiftId} onClick={() => void api.download(`/reports/${shiftId}.csv`, `demo-shift-${shiftId}.csv`)}><Download />CSV</button>{canApprove && <button className="button button--primary" type="button" disabled={approving || !shiftId} onClick={() => void approve()}><CheckCircle2 />Утвердить смену</button>}</>} />
    <div className="report-toolbar"><label className="field"><span>Смена</span><select value={shiftId} onChange={(event) => setShiftId(event.target.value)}>{shifts.data?.items.map((shift) => <option key={shift.id} value={shift.id}>{shift.code} · {formatDate(shift.production_date)} · {humanize(shift.approval_status)}</option>)}</select></label><p>Экспорт сохраняет активный срез, версию и маркировку демоданных.</p></div>
    {message && <div className="inline-alert inline-alert--success" role="status"><CheckCircle2 /><p>{message}</p></div>}
    {error && <div className="inline-alert inline-alert--danger" role="alert"><ShieldAlert /><p>{error}</p></div>}
    {report.loading ? <LoadingState rows={9} /> : report.error ? <ErrorState message={report.error.message} onRetry={() => void report.reload()} /> : !report.data ? <EmptyState title="Выберите смену" message="Отчёт формируется только по данным выбранной версии." /> : <>
      <section className="report-status context-bar"><div><span>Закрытие смены</span><StatusBadge tone={toneForStatus(report.data.calculation.approval_status)}>{humanize(report.data.calculation.approval_status)}</StatusBadge></div><div><span>Готовность KPI</span><StatusBadge tone={toneForStatus(report.data.calculation.maturity_state)}>{humanize(report.data.calculation.maturity_state)}</StatusBadge></div><div><span>Версия расчёта</span><strong>{report.data.calculation.version}</strong></div><div><span>Сформирован</span><strong>{formatDateTime(report.data.calculation.calculated_at)}</strong></div></section>
      <section className="workspace-section"><SectionHeader title="Компоненты" description="A_volume может быть выше 100%, но composite использует только A_plan." /><MetricStrip items={metrics} /></section>
      {report.data.calculation.reason_flags.length > 0 && <div className="inline-alert inline-alert--warning"><ShieldAlert /><div><strong>Ограничения отчёта</strong><ul>{report.data.calculation.reason_flags.map((item) => <li key={item}>{humanize(item)}</li>)}</ul></div></div>}
      <section className="workspace-section"><SectionHeader title="Раздельные контуры" description="Производственное качество и корректность решений ОТК не смешиваются." /><div className="quality-summary"><div><span>Производство</span><strong>{humanize(String(report.data.calculation.production.status ?? "—"))}</strong><small>Q первого предъявления</small></div><div><span>ОТК</span><strong>{humanize(String(report.data.calculation.otk.status ?? "—"))}</strong><small>независимый аудит решений</small></div><div><span>Снимок</span><strong>{report.data.frozen ? "Зафиксирован" : "Текущий"}</strong><small>{report.data.snapshot_id ?? "без snapshot"}</small></div></div></section>
      <section className="report-details">
        <details className="workspace-section" open><summary>Входы расчёта <span>{Object.keys(report.data.calculation.inputs).length}</span></summary><div className="details-content"><dl className="input-ledger">{Object.entries(report.data.calculation.inputs).map(([key, value]) => <div key={key}><dt>{humanize(key)}</dt><dd>{value === null ? "—" : String(value)}</dd></div>)}</dl></div></details>
        <details className="workspace-section"><summary>Версии и трассировка <span>{Object.keys(report.data.calculation.trace).length}</span></summary><div className="details-content"><dl className="input-ledger">{Object.entries(report.data.calculation.trace).map(([key, value]) => <div key={key}><dt>{humanize(key)}</dt><dd><code>{value === null ? "—" : String(value)}</code></dd></div>)}</dl></div></details>
      </section>
    </>}
  </div>;
}

