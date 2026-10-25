import { AlertTriangle, CheckCircle2, CircleStop, RefreshCw, RotateCcw, Wrench } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import { clearCorruptedPending, inspectPendingScan, PENDING_KEY } from "../api/pending";
import { clearCorruptedQcPending, inspectQcPending, QC_PENDING_KEY } from "../api/qcPending";
import type { ForemanProblem, ForemanShiftSummary, OperationEventResult } from "../api/types";
import { useAuth } from "../app/AuthContext";
import { formatDateTime, humanize } from "../app/format";
import { useResource } from "../app/useResource";
import { EmptyState, ErrorState, LoadingState } from "../components/PageState";
import { StatusBadge, toneForStatus } from "../components/StatusBadge";

function assignmentLabel(status: string) {
  return status === "ACTIVE" ? "Назначение действует" : status === "ENDED" ? "Назначение завершено" : humanize(status);
}

function problemLabel(problem: ForemanProblem) {
  return problem.kind === "NEEDS_REVIEW" ? "Нужна проверка" : "Отклонено сервером";
}

async function fingerprint(raw: string) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(raw));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function ForemanWorkspacePage() {
  const { user } = useAuth();
  const summary = useResource(() => api.get<ForemanShiftSummary>("/me/foreman-shift-summary?limit=10"), []);
  const [workerLocal, setWorkerLocal] = useState(() => inspectPendingScan());
  const [qcLocal, setQcLocal] = useState(() => inspectQcPending());
  const [workerReason, setWorkerReason] = useState("");
  const [qcReason, setQcReason] = useState("");
  const [localBusy, setLocalBusy] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const canResolveLocal = Boolean(user?.capabilities.includes("resolve_pending") || user?.capabilities.includes("admin"));

  useEffect(() => {
    function syncLocal(event: StorageEvent) {
      if (event.key === PENDING_KEY) setWorkerLocal(inspectPendingScan());
      if (event.key === QC_PENDING_KEY) setQcLocal(inspectQcPending());
    }
    window.addEventListener("storage", syncLocal);
    return () => window.removeEventListener("storage", syncLocal);
  }, []);

  async function resolveCorruption(kind: "worker" | "qc") {
    const state = kind === "worker" ? workerLocal : qcLocal;
    const reason = kind === "worker" ? workerReason : qcReason;
    if (!state.corruption || !reason.trim() || !canResolveLocal) return;
    setLocalBusy(true); setLocalError(null);
    try {
      await api.post<OperationEventResult>("/operation-events/resolve-local-corruption", {
        reason: reason.trim(), fingerprint: await fingerprint(state.corruption.raw),
      });
      if (kind === "worker") {
        clearCorruptedPending(state.corruption.raw); setWorkerLocal(inspectPendingScan()); setWorkerReason("");
      } else {
        clearCorruptedQcPending(state.corruption.raw); setQcLocal(inspectQcPending()); setQcReason("");
      }
    } catch (caught) { setLocalError(caught instanceof Error ? caught.message : "Не удалось разрешить повреждённую локальную запись"); }
    finally { setLocalBusy(false); }
  }

  if (summary.loading) return <div className="page foreman-page"><LoadingState rows={8} label="Загружаем данные ряда" /></div>;
  if (summary.error) return <div className="page foreman-page"><ErrorState title="Не удалось загрузить данные ряда" message={summary.error.message} onRetry={() => void summary.reload()} /></div>;
  if (!summary.data) return null;

  const data = summary.data;
  const hasLocalContext = Boolean(workerLocal.pending || workerLocal.corruption || qcLocal.pending || qcLocal.corruption);

  return <div className="page foreman-page">
    <h1 className="sr-only">Рабочее место бригадира</h1>
    <header className="foreman-heading"><div><span>Ряд</span><strong>{data.row.name}</strong></div><div><span>Смена</span><strong>{data.shift.code}</strong></div><button className="icon-button" type="button" aria-label="Обновить данные ряда" onClick={() => void summary.reload()}><RefreshCw /></button></header>

    <section className="workspace-section foreman-block foreman-roster" aria-labelledby="foreman-roster-title">
      <div className="section-header"><div><h2 id="foreman-roster-title">Состав ряда</h2><p>Назначения смены, а не онлайн-присутствие</p></div><StatusBadge tone="info">Назначений: {data.roster.length}</StatusBadge></div>
      {data.roster.length === 0 ? <EmptyState title="Состав не назначен" message="Для этого ряда в активной смене нет сохранённых назначений." /> : <ul className="foreman-roster-list">{data.roster.map((item) => { const employeeName = item.employee?.display_name ?? "Сотрудник не найден"; return <li key={item.assignment_id}><span className="foreman-avatar" aria-hidden="true">{employeeName.slice(0, 2).toUpperCase()}</span><div className="foreman-roster-person"><strong>{employeeName}</strong></div><div><span>Операция</span><strong>{item.route_step?.name ?? "Не назначена"}</strong></div><div><span>Рабочее место</span><strong>{item.workstation?.name ?? "Не назначено"}</strong></div><div className="foreman-assignment-state"><StatusBadge compact tone={item.assignment_status === "ACTIVE" ? "success" : "neutral"}>{assignmentLabel(item.assignment_status)}</StatusBadge><small>{formatDateTime(item.starts_at)}{item.ends_at ? ` — ${formatDateTime(item.ends_at)}` : ""}</small></div></li>; })}</ul>}
    </section>

    <section className="workspace-section foreman-block foreman-output" aria-labelledby="foreman-output-title">
      <div className="foreman-output-copy"><h2 id="foreman-output-title">Выполнено за смену</h2><strong data-testid="foreman-primary-count">{data.primary_completed}</strong><p>первичных операций ряда</p></div><div className="foreman-output-rework"><RotateCcw aria-hidden="true" /><div><span>Переделка</span><strong data-testid="foreman-rework-count">{data.rework_completed}</strong><small>операций отдельно</small></div></div><p className="foreman-method-note">Серверный итог по ряду за всю смену; изменения состава его не сбрасывают.</p>
    </section>

    <section className="workspace-section foreman-block foreman-problems" aria-labelledby="foreman-problems-title">
      <div className="section-header"><div><h2 id="foreman-problems-title">Проблемные сканы</h2><p>Последние зафиксированные сервером ошибки за смену · до 10</p></div>{data.problems.length > 0 && <StatusBadge tone="warning">Показано {data.problems.length}</StatusBadge>}</div>
      {localError && <div className="inline-alert inline-alert--danger" role="alert"><AlertTriangle /><p>{localError}</p></div>}
      {hasLocalContext && <div className="foreman-local-context"><div className="foreman-local-context__title"><CircleStop /><div><strong>На этом устройстве есть незавершённая локальная запись</strong><p>Она не показывает состояние других рабочих мест и не входит в серверную историю ниже.</p></div></div>{workerLocal.pending && <div className="foreman-local-item"><StatusBadge tone="warning">Рабочий скан</StatusBadge><div><strong>{workerLocal.pending.body.subject_qr}</strong><p>Автор: {workerLocal.pending.actorName}. Для продолжения войдите под исходным работником и проверьте статус.</p></div></div>}{qcLocal.pending && <div className="foreman-local-item"><StatusBadge tone="warning">Проверка ОТК</StatusBadge><div><strong>{qcLocal.pending.body.subject_qr}</strong><p>Автор: {qcLocal.pending.actorName}. Продолжить проверку должен исходный контролёр.</p></div></div>}{workerLocal.corruption && <div className="foreman-local-item foreman-local-item--corrupt"><StatusBadge tone="danger">Повреждённый рабочий скан</StatusBadge><div><p>Можно разрешить только локальную запись с обязательной причиной. Это не отменяет неизвестный серверный запрос.</p>{canResolveLocal ? <div className="foreman-local-resolution"><label className="field"><span>Причина</span><input value={workerReason} onChange={(event) => setWorkerReason(event.target.value)} /></label><button className="button button--secondary" type="button" disabled={localBusy || !workerReason.trim()} onClick={() => void resolveCorruption("worker")}>Зафиксировать и очистить</button></div> : <StatusBadge tone="danger">Нужен уполномоченный бригадир</StatusBadge>}</div></div>}{qcLocal.corruption && <div className="foreman-local-item foreman-local-item--corrupt"><StatusBadge tone="danger">Повреждённая проверка ОТК</StatusBadge><div><p>Разрешение относится только к данным этого браузера и фиксируется в аудите.</p>{canResolveLocal ? <div className="foreman-local-resolution"><label className="field"><span>Причина</span><input value={qcReason} onChange={(event) => setQcReason(event.target.value)} /></label><button className="button button--secondary" type="button" disabled={localBusy || !qcReason.trim()} onClick={() => void resolveCorruption("qc")}>Зафиксировать и очистить</button></div> : <StatusBadge tone="danger">Нужен уполномоченный бригадир</StatusBadge>}</div></div>}</div>}
      {data.problems.length === 0 ? <div className="foreman-empty"><CheckCircle2 /><div><strong>Нет сохранённых проблемных сканов в этом ряду</strong><p>Неподтверждённые сканы с других устройств здесь не видны.</p></div></div> : <ol className="foreman-problem-list">{data.problems.map((problem) => <li key={problem.id} data-problem-id={problem.id}><span className="foreman-problem-icon"><AlertTriangle /></span><div><div className="foreman-problem-meta"><StatusBadge compact tone={problem.kind === "NEEDS_REVIEW" ? "warning" : "danger"}>{problemLabel(problem)}</StatusBadge><time dateTime={problem.occurred_at}>{formatDateTime(problem.occurred_at)}</time></div><strong>{problem.message}</strong><p>{problem.qr ?? "QR не сохранён"}{problem.operation ? ` · ${problem.operation.name}` : ""}{problem.worker ? ` · ${problem.worker.display_name}` : ""}</p></div></li>)}</ol>}
    </section>

    <section className="workspace-section foreman-block foreman-reworks" aria-labelledby="foreman-reworks-title">
      <div className="section-header"><div><h2 id="foreman-reworks-title">Переделки ряда</h2><p>Последние заказы с подтверждённой привязкой · до 10</p></div>{data.reworks.length > 0 && <StatusBadge tone="info">Показано {data.reworks.length}</StatusBadge>}</div>
      {data.reworks.length === 0 ? <div className="foreman-empty"><Wrench /><div><strong>Переделок для ряда нет</strong><p>Заказы без назначенного ряда не приписываются всем сборочным рядам.</p></div></div> : <ul className="foreman-rework-list">{data.reworks.map((item) => <li key={item.id} data-rework-id={item.id}><div><code>{item.qr ?? "QR не найден"}</code><strong>{item.reason}</strong><small>{item.requested_route_step?.name ?? "Ряд ещё не назначен"} · {formatDateTime(item.created_at)}</small></div><StatusBadge compact tone={toneForStatus(item.status)}>{humanize(item.status)}</StatusBadge></li>)}</ul>}
    </section>
  </div>;
}
