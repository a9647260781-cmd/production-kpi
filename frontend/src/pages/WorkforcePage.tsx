import { Clock3, Plus, RefreshCw, UsersRound } from "lucide-react";
import { useMemo, useState } from "react";
import { api, query } from "../api/client";
import type { Assignment, Bootstrap, Employee, ListResponse, TimeCategory, TimeEntry } from "../api/types";
import { useAuth } from "../app/AuthContext";
import { canAccess } from "../app/capabilities";
import { formatDateTime, formatDecimal, humanize } from "../app/format";
import { useResource } from "../app/useResource";
import { AccessDenied } from "../components/AccessDenied";
import { DataTable, type Column } from "../components/DataTable";
import { EmptyState, ErrorState, LoadingState } from "../components/PageState";
import { PageHeader, SectionHeader } from "../components/PageHeader";
import { StatusBadge, toneForStatus } from "../components/StatusBadge";

const categories: TimeCategory[] = ["PRIMARY", "REWORK", "WAITING", "SETUP", "SUPPORT", "UNAVAILABLE"];

export function WorkforcePage() {
  const { user } = useAuth();
  const bootstrap = useResource(() => api.get<Bootstrap>("/bootstrap"), []);
  const shiftId = bootstrap.data?.active_shift?.id ?? "";
  const assignments = useResource(() => shiftId ? api.get<ListResponse<Assignment>>(`/assignments${query({ shift_id: shiftId })}`) : Promise.resolve({ items: [], total: 0 }), [shiftId]);
  const entries = useResource(() => shiftId ? api.get<ListResponse<TimeEntry>>(`/time-entries${query({ shift_id: shiftId })}`) : Promise.resolve({ items: [], total: 0 }), [shiftId]);
  const employees = useResource(() => api.get<ListResponse<Employee>>("/employees").catch(() => ({ items: bootstrap.data?.employees ?? [], total: bootstrap.data?.employees?.length ?? 0 })), [bootstrap.data?.version]);
  const [showAssignment, setShowAssignment] = useState(false);
  const [employeeId, setEmployeeId] = useState("");
  const [rowId, setRowId] = useState("");
  const [workstationId, setWorkstationId] = useState("");
  const [stepId, setStepId] = useState("");
  const [transferFromId, setTransferFromId] = useState("");
  const [entryAssignmentId, setEntryAssignmentId] = useState("");
  const [category, setCategory] = useState<TimeCategory>("PRIMARY");
  const [hours, setHours] = useState("");
  const [comment, setComment] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const stations = useMemo(() => bootstrap.data?.workstations.filter((item) => !rowId || item.row_id === rowId) ?? [], [bootstrap.data, rowId]);
  const steps = useMemo(() => {
    const row = bootstrap.data?.rows.find((item) => item.id === rowId);
    return bootstrap.data?.route_steps.filter((item) => !rowId || item.row_id === rowId || (item.row_id === null && row?.category === "ASSEMBLY")) ?? [];
  }, [bootstrap.data, rowId]);
  const canAssignments = Boolean(user?.capabilities.includes("manage_assignments") || user?.capabilities.includes("admin"));
  const canTime = Boolean(user?.capabilities.includes("manage_time_entries") || user?.capabilities.includes("admin"));

  if (!user || !canAccess(user, "workforce")) return <AccessDenied />;
  if (bootstrap.loading) return <div className="page"><LoadingState rows={7} /></div>;
  if (bootstrap.error) return <div className="page"><ErrorState message={bootstrap.error.message} onRetry={() => void bootstrap.reload()} /></div>;

  async function createAssignment(event: React.FormEvent) {
    event.preventDefault(); if (!shiftId) return;
    setSaving(true); setFormError(null); setMessage(null);
    try {
      const startsAt = new Date();
      const endsAt = new Date(startsAt.getTime() + 8 * 60 * 60 * 1000);
      await api.post(`/shifts/${shiftId}/assignments`, { employee_id: employeeId, row_id: rowId, workstation_id: workstationId, route_step_id: stepId, starts_at: startsAt.toISOString(), ends_at: endsAt.toISOString(), transfer_from_assignment_id: transferFromId || null });
      setMessage(transferFromId ? "Перевод выполнен: прежнее назначение завершено сервером, новое открыто без перепривязки истории." : "Назначение создано. Прошлые события сотрудника не перепривязаны."); setTransferFromId(""); setShowAssignment(false); await assignments.reload();
    } catch (caught) { setFormError(caught instanceof Error ? caught.message : "Не удалось создать назначение"); }
    finally { setSaving(false); }
  }

  async function createTimeEntry(event: React.FormEvent) {
    event.preventDefault(); if (!shiftId) return;
    setSaving(true); setFormError(null); setMessage(null);
    try {
      await api.post("/time-entries", { assignment_id: entryAssignmentId, category, hours, source: "DEMO", reason: comment.trim() || null });
      setMessage("Часы сохранены новой версией. Зависимый расчёт отмечен на пересмотр."); setHours(""); setComment(""); await entries.reload();
    } catch (caught) { setFormError(caught instanceof Error ? caught.message : "Не удалось сохранить часы"); }
    finally { setSaving(false); }
  }

  const assignmentColumns: Column<Assignment>[] = [
    { key: "employee", title: "Сотрудник", render: (row) => <strong>{employees.data?.items.find((item) => item.id === row.employee_id)?.display_name ?? row.employee_id}</strong> },
    { key: "row", title: "Ряд / место", render: (row) => <>{bootstrap.data?.rows.find((item) => item.id === row.row_id)?.name ?? row.row_id}<small className="table-subline">{bootstrap.data?.workstations.find((item) => item.id === row.workstation_id)?.name ?? row.workstation_id}</small></> },
    { key: "step", title: "Операция", render: (row) => bootstrap.data?.route_steps.find((item) => item.id === row.route_step_id)?.name ?? row.route_step_id },
    { key: "period", title: "Интервал", render: (row) => <>{formatDateTime(row.starts_at)}<small className="table-subline">до {formatDateTime(row.ends_at)}</small></> },
    { key: "status", title: "Статус", render: (row) => <StatusBadge compact tone={toneForStatus(row.status)}>{humanize(row.status)}</StatusBadge> },
  ];
  const entryColumns: Column<TimeEntry>[] = [
    { key: "employee", title: "Назначение", render: (row) => <strong>{row.assignment_id.slice(0, 8)}</strong> },
    { key: "category", title: "Категория", render: (row) => humanize(row.category) },
    { key: "hours", title: "Часы", align: "right", render: (row) => <strong className="tabular">{formatDecimal(row.hours)}</strong> },
    { key: "source", title: "Источник", render: (row) => row.source },
    { key: "version", title: "Версия", render: (row) => `v${row.version}` },
    { key: "status", title: "Статус", render: (row) => <StatusBadge compact tone={toneForStatus(row.approval_status)}>{humanize(row.approval_status)}</StatusBadge> },
  ];

  return <div className="page">
    <PageHeader title="Сменный состав и часы" description="Назначения определяют контекст операций. H_accounted строится из записей времени, а не из интервалов между сканами." meta={<span className="demo-marker">ДЕМО</span>} actions={<button className="button button--secondary" type="button" onClick={() => void Promise.all([assignments.reload(), entries.reload()])}><RefreshCw />Обновить</button>} />
    {message && <div className="inline-alert inline-alert--success" role="status"><UsersRound /><p>{message}</p></div>}
    {formError && <div className="inline-alert inline-alert--danger" role="alert"><Clock3 /><p>{formError}</p></div>}
    <section className="workspace-section">
      <SectionHeader title="Состав смены" description={`${assignments.data?.total ?? 0} назначений`} action={canAssignments ? <button className="button button--primary" type="button" onClick={() => setShowAssignment((value) => !value)}><Plus />Назначить</button> : undefined} />
      {showAssignment && <form className="inline-form" onSubmit={createAssignment}>
        <label className="field"><span>Сотрудник</span><select value={employeeId} onChange={(event) => setEmployeeId(event.target.value)} required><option value="">Выберите</option>{employees.data?.items.map((item) => <option key={item.id} value={item.id}>{item.display_name} · {item.personnel_no}</option>)}</select></label>
        <label className="field"><span>Ряд</span><select value={rowId} onChange={(event) => setRowId(event.target.value)} required><option value="">Выберите</option>{bootstrap.data?.rows.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label className="field"><span>Место</span><select value={workstationId} onChange={(event) => setWorkstationId(event.target.value)} required><option value="">Выберите</option>{stations.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label className="field"><span>Операция</span><select value={stepId} onChange={(event) => setStepId(event.target.value)} required><option value="">Выберите</option>{steps.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        <label className="field"><span>Перевести из назначения</span><select value={transferFromId} onChange={(event) => setTransferFromId(event.target.value)}><option value="">Не переводить</option>{assignments.data?.items.filter((item) => item.status === "ACTIVE").map((item) => <option key={item.id} value={item.id}>{employees.data?.items.find((employee) => employee.id === item.employee_id)?.display_name ?? item.employee_id} · {bootstrap.data?.rows.find((row) => row.id === item.row_id)?.name ?? item.row_id}</option>)}</select></label>
        <button className="button button--primary" disabled={saving} type="submit">Сохранить</button>
      </form>}
      {assignments.loading ? <LoadingState rows={5} /> : assignments.error ? <ErrorState message={assignments.error.message} onRetry={() => void assignments.reload()} /> : assignments.data?.items.length ? <DataTable columns={assignmentColumns} rows={assignments.data.items} getKey={(row) => row.id} caption="Назначения смены" /> : <EmptyState title="Состав не назначен" message="Добавьте сотрудников, рабочие места и операции до начала смены." />}
    </section>
    <section className="workforce-grid">
      <div className="workspace-section">
        <SectionHeader title="Учтённые часы" description="Категории и версии входят в расшифровку производительности." />
        {entries.loading ? <LoadingState rows={4} /> : entries.error ? <ErrorState message={entries.error.message} onRetry={() => void entries.reload()} /> : entries.data?.items.length ? <DataTable columns={entryColumns} rows={entries.data.items} getKey={(row) => row.id} caption="Учтённые часы" /> : <EmptyState title="Часы не внесены" message="Без подтверждённых часов производительность и итоговый KPI не рассчитываются." />}
      </div>
      {canTime && <form className="workspace-section time-entry-form" onSubmit={createTimeEntry}>
        <SectionHeader title="Добавить часы" description="Изменение создаёт новую версию, а не переписывает историю." />
        <label className="field"><span>Назначение</span><select value={entryAssignmentId} onChange={(event) => setEntryAssignmentId(event.target.value)} required><option value="">Выберите</option>{assignments.data?.items.map((item) => <option key={item.id} value={item.id}>{employees.data?.items.find((employee) => employee.id === item.employee_id)?.display_name ?? item.employee_id} · {bootstrap.data?.rows.find((row) => row.id === item.row_id)?.name ?? item.row_id}</option>)}</select></label>
        <label className="field"><span>Категория</span><select value={category} onChange={(event) => setCategory(event.target.value as TimeCategory)}>{categories.map((item) => <option key={item} value={item}>{humanize(item)}</option>)}</select></label>
        <label className="field"><span>Человеко-часы</span><input inputMode="decimal" value={hours} onChange={(event) => setHours(event.target.value.replace(",", "."))} placeholder="7.5" required /></label>
        <label className="field"><span>Комментарий</span><textarea rows={3} value={comment} onChange={(event) => setComment(event.target.value)} /></label>
        <button className="button button--primary" disabled={saving || !entryAssignmentId || !hours} type="submit">Сохранить часы</button>
      </form>}
    </section>
  </div>;
}

