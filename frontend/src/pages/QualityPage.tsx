import { AlertTriangle, CircleStop, ClipboardCheck, Plus, RefreshCw, SearchCheck, Wrench } from "lucide-react";
import { useEffect, useState } from "react";
import { api, query } from "../api/client";
import { inspectPendingScan, PENDING_KEY } from "../api/pending";
import { clearCorruptedQcPending, inspectQcPending, QC_PENDING_KEY } from "../api/qcPending";
import type { Bootstrap, ListResponse, OperationEventResult, QualityAudit, QualityDecision, ReworkOrder } from "../api/types";
import { useAuth } from "../app/AuthContext";
import { canAccess } from "../app/capabilities";
import { formatDateTime, humanize } from "../app/format";
import { useResource } from "../app/useResource";
import { AccessDenied } from "../components/AccessDenied";
import { DataTable, type Column } from "../components/DataTable";
import { EmptyState, ErrorState, LoadingState } from "../components/PageState";
import { PageHeader, SectionHeader } from "../components/PageHeader";
import { StatusBadge, toneForStatus } from "../components/StatusBadge";

type QualityMode = "decision" | "audit" | "rework";

export function QualityPage() {
  const { user } = useAuth();
  const canDecide = Boolean(user && (user.capabilities.includes("quality_decide") || user.capabilities.includes("admin")));
  const canAudit = Boolean(user && (user.capabilities.includes("quality_audit") || user.capabilities.includes("admin")));
  const canRework = Boolean(user && (user.capabilities.includes("manage_rework") || user.capabilities.includes("admin")));
  const canResolvePending = Boolean(user && (user.capabilities.includes("resolve_pending") || user.capabilities.includes("admin")));
  const bootstrap = useResource(() => api.get<Bootstrap>("/bootstrap"), []);
  const shiftId = bootstrap.data?.active_shift?.id ?? "";
  const decisions = useResource(() => shiftId ? api.get<ListResponse<QualityDecision>>(`/quality/decisions${query({ shift_id: shiftId })}`) : Promise.resolve({ items: [], total: 0 }), [shiftId]);
  const audits = useResource(() => shiftId ? api.get<ListResponse<QualityAudit>>(`/quality/audits${query({ shift_id: shiftId })}`) : Promise.resolve({ items: [], total: 0 }), [shiftId]);
  const reworks = useResource(() => shiftId ? api.get<ListResponse<ReworkOrder>>(`/rework-orders${query({ shift_id: shiftId })}`) : Promise.resolve({ items: [], total: 0 }), [shiftId]);
  const [mode, setMode] = useState<QualityMode>(() => canDecide ? "decision" : canAudit ? "audit" : "rework");
  const [entityQr, setEntityQr] = useState("");
  const [decision, setDecision] = useState<"ACCEPT" | "REJECT">("ACCEPT");
  const [defectCode, setDefectCode] = useState("");
  const [comment, setComment] = useState("");
  const [decisionId, setDecisionId] = useState("");
  const [auditResult, setAuditResult] = useState<"CONFIRMED" | "OVERTURNED">("CONFIRMED");
  const [routeStepId, setRouteStepId] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [qcPendingState, setQcPendingState] = useState(() => inspectQcPending());
  const [workerPendingState, setWorkerPendingState] = useState(() => inspectPendingScan());
  const [corruptionReason, setCorruptionReason] = useState("");

  useEffect(() => {
    function syncPending(event: StorageEvent) {
      if (event.key === QC_PENDING_KEY) setQcPendingState(inspectQcPending());
      if (event.key === PENDING_KEY) setWorkerPendingState(inspectPendingScan());
    }
    window.addEventListener("storage", syncPending);
    return () => window.removeEventListener("storage", syncPending);
  }, []);

  useEffect(() => {
    const permitted = (mode === "decision" && canDecide) || (mode === "audit" && canAudit) || (mode === "rework" && canRework);
    if (!permitted) setMode(canDecide ? "decision" : canAudit ? "audit" : "rework");
  }, [canAudit, canDecide, canRework, mode]);

  if (!user || !canAccess(user, "quality")) return <AccessDenied />;

  async function submit(event: React.FormEvent) {
    event.preventDefault(); if (!shiftId || qcPendingState.pending || qcPendingState.corruption || workerPendingState.pending || workerPendingState.corruption) return;
    setSaving(true); setMessage(null); setError(null);
    try {
      if (mode === "decision") {
        const created = await api.post<{ id: string }>("/quality/decisions", { request_id: crypto.randomUUID(), entity_qr: entityQr.trim(), decision, defect_code: decision === "REJECT" ? defectCode.trim() || null : null, note: comment.trim() || null });
        setDecisionId(created.id);
        setMessage("Решение ОТК сохранено. Найденный дефект не считается штрафом контролёру."); await decisions.reload();
      } else if (mode === "audit") {
        await api.post("/quality/audits", { request_id: crypto.randomUUID(), decision_id: decisionId, result: auditResult, note: comment.trim() || null });
        setMessage("Независимая перепроверка сохранена отдельно от исходного решения."); await audits.reload(); await decisions.reload();
      } else {
        await api.post("/rework-orders", { request_id: crypto.randomUUID(), entity_qr: entityQr.trim(), quality_decision_id: decisionId, requested_route_step_id: routeStepId, reason: comment.trim() });
        setMessage("Переделка открыта отдельным маршрутом и не создаёт второй первичный выпуск."); await reworks.reload();
      }
      setEntityQr(""); setComment(""); setDefectCode("");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Не удалось сохранить действие ОТК"); }
    finally { setSaving(false); }
  }

  async function resolveQcCorruption() {
    if (!qcPendingState.corruption || !corruptionReason.trim()) return;
    setSaving(true); setError(null);
    try {
      const bytes = new TextEncoder().encode(qcPendingState.corruption.raw);
      const digest = await crypto.subtle.digest("SHA-256", bytes);
      const fingerprint = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
      await api.post<OperationEventResult>("/operation-events/resolve-local-corruption", { reason: corruptionReason.trim(), fingerprint });
      clearCorruptedQcPending(qcPendingState.corruption.raw);
      setQcPendingState(inspectQcPending()); setCorruptionReason("");
      setMessage("Повреждённая локальная запись разрешена и зафиксирована в аудите. Серверная проверка этим не отменялась.");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Не удалось разрешить локальную запись"); }
    finally { setSaving(false); }
  }

  const decisionColumns: Column<QualityDecision>[] = [
    { key: "entity", title: "Объект", render: (row) => <code>{row.entity_id.slice(0, 8)}</code> },
    { key: "decision", title: "Решение", render: (row) => <StatusBadge compact tone={row.decision === "ACCEPT" ? "success" : "warning"}>{humanize(row.decision)}</StatusBadge> },
    { key: "defect", title: "Дефект", render: (row) => row.defect_code ?? "—" },
    { key: "inspector", title: "Контролёр", render: (row) => <code>{row.inspector_user_id.slice(0, 8)}</code> },
    { key: "time", title: "Время", render: (row) => formatDateTime(row.created_at) },
  ];
  const auditColumns: Column<QualityAudit>[] = [
    { key: "decision", title: "Решение", render: (row) => <code>{row.decision_id.slice(0, 8)}</code> },
    { key: "result", title: "Результат перепроверки", render: (row) => <StatusBadge compact tone={row.result === "CONFIRMED" ? "success" : "danger"}>{humanize(row.result)}</StatusBadge> },
    { key: "auditor", title: "Аудитор", render: (row) => <code>{row.auditor_user_id.slice(0, 8)}</code> },
    { key: "time", title: "Время", render: (row) => formatDateTime(row.created_at) },
  ];

  return <div className="page">
    <PageHeader title="ОТК и переделки" description="Производственное качество и корректность решений ОТК оцениваются раздельно." meta={<span className="demo-marker">ДЕМО</span>} actions={<button className="button button--secondary" type="button" onClick={() => void Promise.all([decisions.reload(), audits.reload(), reworks.reload()])}><RefreshCw />Обновить</button>} />
    {message && <div className="inline-alert inline-alert--success" role="status"><ClipboardCheck /><p>{message}</p></div>}
    {error && <div className="inline-alert inline-alert--danger" role="alert"><SearchCheck /><p>{error}</p></div>}
    {qcPendingState.corruption && <section className="pending-lock pending-lock--corrupt"><span className="pending-lock__icon"><AlertTriangle /></span><div><StatusBadge tone="danger">Ошибка локальной записи ОТК</StatusBadge><h2>Новые решения заблокированы</h2><p>Разрешение удалит только повреждённую локальную запись и будет зафиксировано в аудите. Оно не отменяет неизвестный серверный запрос.</p></div><div className="pending-lock__actions">{canResolvePending ? <><label className="field"><span>Причина разрешения</span><input value={corruptionReason} onChange={(event) => setCorruptionReason(event.target.value)} /></label><button className="button button--primary" type="button" disabled={saving || !corruptionReason.trim()} onClick={() => void resolveQcCorruption()}>Зафиксировать и очистить</button></> : <StatusBadge tone="danger">Нужен бригадир или администратор</StatusBadge>}</div></section>}
    {qcPendingState.pending && <section className="pending-lock"><span className="pending-lock__icon"><CircleStop /></span><div><StatusBadge tone="warning">Проверка ОТК не подтверждена</StatusBadge><h2>Нужен исходный контролёр</h2><p>Проверка QR {qcPendingState.pending.body.subject_qr} должна быть повторена с тем же UUID под учётной записью {qcPendingState.pending.actorName}.</p></div></section>}
    {(workerPendingState.pending || workerPendingState.corruption) && <section className="pending-lock"><span className="pending-lock__icon"><CircleStop /></span><div><StatusBadge tone="warning">Операция не завершена</StatusBadge><h2>Сначала разрешите рабочий скан</h2><p>Пока другое QR-действие не подтверждено, новое решение ОТК недоступно.</p></div></section>}
    <section className="quality-summary workspace-section">
      <div><span>Решений ОТК</span><strong>{decisions.data?.total ?? "—"}</strong><small>характеризуют входящий поток</small></div>
      <div><span>Независимых проверок</span><strong>{audits.data?.total ?? "—"}</strong><small>основа escape / false reject</small></div>
      <div><span>Открытых переделок</span><strong>{reworks.data?.items.filter((item) => !["REINSPECTED", "CANCELLED"].includes(item.status)).length ?? "—"}</strong><small>не увеличивают первичный выпуск</small></div>
    </section>
    {(canDecide || canAudit || canRework) && <section className="workspace-section quality-entry">
      <SectionHeader title="Новое действие" description="Доступные действия определяются полномочиями backend." />
      <div className="segmented-control" role="tablist" aria-label="Тип действия">
        {canDecide && <button type="button" role="tab" aria-selected={mode === "decision"} onClick={() => setMode("decision")}><ClipboardCheck />Решение ОТК</button>}
        {canAudit && <button type="button" role="tab" aria-selected={mode === "audit"} onClick={() => setMode("audit")}><SearchCheck />Независимый аудит</button>}
        {canRework && <button type="button" role="tab" aria-selected={mode === "rework"} onClick={() => setMode("rework")}><Wrench />Переделка</button>}
      </div>
      <form className="inline-form" onSubmit={submit}>
        {mode !== "audit" && <label className="field"><span>QR объекта</span><input value={entityQr} onChange={(event) => setEntityQr(event.target.value)} required /></label>}
        {mode === "decision" && <><label className="field"><span>Решение</span><select value={decision} onChange={(event) => setDecision(event.target.value as "ACCEPT" | "REJECT")}><option value="ACCEPT">Принято</option><option value="REJECT">Отклонено</option></select></label>{decision === "REJECT" && <label className="field"><span>Код дефекта</span><input value={defectCode} onChange={(event) => setDefectCode(event.target.value)} required /></label>}</>}
        {mode === "audit" && <><label className="field"><span>Исходное решение</span><select value={decisionId} onChange={(event) => setDecisionId(event.target.value)} required><option value="">Выберите</option>{decisions.data?.items.map((item) => <option value={item.id} key={item.id}>{item.entity_id.slice(0, 8)} · {humanize(item.decision)}</option>)}</select></label><label className="field"><span>Результат</span><select value={auditResult} onChange={(event) => setAuditResult(event.target.value as typeof auditResult)}><option value="CONFIRMED">Подтверждено</option><option value="OVERTURNED">Решение отменено</option></select></label></>}
        {mode === "rework" && <><label className="field"><span>Решение с отказом</span><select value={decisionId} onChange={(event) => setDecisionId(event.target.value)} required><option value="">Выберите</option>{decisions.data?.items.filter((item) => item.decision === "REJECT").map((item) => <option value={item.id} key={item.id}>{item.entity_id.slice(0, 8)} · {item.defect_code ?? "дефект"}</option>)}</select></label><label className="field"><span>Повторная операция</span><select value={routeStepId} onChange={(event) => setRouteStepId(event.target.value)} required><option value="">Выберите</option>{bootstrap.data?.route_steps.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label></>}
        <label className="field field--grow"><span>{mode === "rework" ? "Причина переделки" : "Комментарий"}</span><input value={comment} onChange={(event) => setComment(event.target.value)} required={mode === "rework"} /></label>
        <button className="button button--primary" disabled={saving || Boolean(qcPendingState.pending || qcPendingState.corruption || workerPendingState.pending || workerPendingState.corruption)} type="submit"><Plus />Сохранить</button>
      </form>
    </section>}
    <section className="workspace-section">
      <SectionHeader title="Решения ОТК" description="Найденный дефект снижает производственное Q, но не штрафует контролёра." />
      {decisions.loading ? <LoadingState rows={5} /> : decisions.error ? <ErrorState message={decisions.error.message} onRetry={() => void decisions.reload()} /> : decisions.data?.items.length ? <DataTable columns={decisionColumns} rows={decisions.data.items} getKey={(row) => row.id} caption="Решения ОТК" /> : <EmptyState title="Решений пока нет" message="Контролёр может зафиксировать первое решение по QR объекта." />}
    </section>
    <section className="quality-grid">
      <div className="workspace-section">
        <SectionHeader title="Независимый аудит" description="Escape и false reject показываются отдельно со своими знаменателями." />
        {audits.loading ? <LoadingState rows={3} /> : audits.error ? <ErrorState message={audits.error.message} onRetry={() => void audits.reload()} /> : audits.data?.items.length ? <DataTable columns={auditColumns} rows={audits.data.items} getKey={(row) => row.id} caption="Независимые проверки" /> : <EmptyState title="Аудит не начат" message="Отсутствие перепроверок не означает 100% корректности решений." />}
      </div>
      <div className="workspace-section">
        <SectionHeader title="Переделки" />
        {reworks.loading ? <LoadingState rows={3} /> : reworks.error ? <ErrorState message={reworks.error.message} onRetry={() => void reworks.reload()} /> : reworks.data?.items.length ? <ul className="compact-list">{reworks.data.items.map((item) => <li key={item.id}><div><code>{item.entity_id.slice(0, 8)}</code><strong>{item.reason}</strong><small>{formatDateTime(item.created_at)}</small></div><StatusBadge compact tone={toneForStatus(item.status)}>{humanize(item.status)}</StatusBadge></li>)}</ul> : <EmptyState title="Открытых переделок нет" message="Повторная операция появится здесь отдельным связанным маршрутом." />}
      </div>
    </section>
  </div>;
}

