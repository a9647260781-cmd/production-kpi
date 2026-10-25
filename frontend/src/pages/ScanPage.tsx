import { AlertTriangle, CheckCircle2, CircleStop, Clock3, Keyboard, LoaderCircle, LogIn, QrCode, RefreshCw, RotateCcw, ScanLine, UserRound } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { annotatePendingError, clearCorruptedPending, clearPendingScan, createPendingScan, inspectPendingScan, isServerAcknowledgement, PENDING_KEY, readPendingScan, type PendingScan } from "../api/pending";
import { inspectQcPending, QC_PENDING_KEY } from "../api/qcPending";
import type { Bootstrap, ListResponse, OperationEventBody, OperationEventResult, ReworkOrder, TrackedEntity, WorkerShiftActivity, WorkerShiftActivityEvent, WorkSession } from "../api/types";
import { useAuth } from "../app/AuthContext";
import { canAccess } from "../app/capabilities";
import { formatDateTime, humanize } from "../app/format";
import { useResource } from "../app/useResource";
import { AccessDenied } from "../components/AccessDenied";
import { ErrorState, LoadingState } from "../components/PageState";
import { PageHeader, SectionHeader } from "../components/PageHeader";
import { StatusBadge, toneForStatus } from "../components/StatusBadge";

function workerEventPresentation(event: WorkerShiftActivityEvent) {
  if (event.corrected || event.display_status === "CORRECTED") return { label: "Исправлено", tone: "warning" as const };
  if (event.status === "CANCELLED") return { label: "Отменено", tone: "danger" as const };
  if (event.status === "NEEDS_REVIEW" || event.status === "PENDING") return { label: "Нужна проверка", tone: "warning" as const };
  if (event.status === "ACCEPTED" && (event.display_status === "ACCEPTED_REWORK" || event.attempt_type === "REWORK")) return { label: "Переделка", tone: "info" as const };
  if (event.status === "ACCEPTED" && event.display_status === "ACCEPTED_PRIMARY") return { label: "Принято", tone: "success" as const };
  return { label: humanize(event.display_status || event.status), tone: toneForStatus(event.status) };
}

export function ScanPage() {
  const { user } = useAuth();
  const isWorkerView = Boolean(user?.roles.length && user.roles.every((role) => role.name === "WORKER"));
  const bootstrap = useResource(() => api.get<Bootstrap>("/bootstrap"), []);
  const sessions = useResource(() => api.get<ListResponse<WorkSession>>("/work-sessions"), []);
  const reworks = useResource(() => api.get<ListResponse<ReworkOrder>>("/rework-orders"), []);
  const activity = useResource(
    () => isWorkerView ? api.get<WorkerShiftActivity>("/me/shift-activity?limit=10") : Promise.resolve(null as unknown as WorkerShiftActivity),
    [isWorkerView],
  );
  const [session, setSession] = useState<WorkSession | null>(null);
  const [rowId, setRowId] = useState("");
  const [workstationId, setWorkstationId] = useState("");
  const [routeStepId, setRouteStepId] = useState("");
  const [qr, setQr] = useState("");
  const [attemptType, setAttemptType] = useState<"PRIMARY" | "REWORK">("PRIMARY");
  const [authorizedRework, setAuthorizedRework] = useState<ReworkOrder | null>(null);
  const initialPending = useMemo(() => inspectPendingScan(), []);
  const [pending, setPending] = useState<PendingScan | null>(initialPending.pending);
  const [corruption, setCorruption] = useState(initialPending.corruption);
  const [foreignQcPending, setForeignQcPending] = useState(() => inspectQcPending());
  const [result, setResult] = useState<OperationEventResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [corruptionReason, setCorruptionReason] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const activeSubmissionIdRef = useRef<string | null>(null);

  useEffect(() => {
    function syncAcrossTabs(event: StorageEvent) {
      if (event.key === PENDING_KEY) {
        const inspection = inspectPendingScan();
        setPending(inspection.pending);
        setCorruption(inspection.corruption);
        if (inspection.pending || inspection.corruption) setQr("");
      }
      if (event.key === QC_PENDING_KEY) {
        const inspection = inspectQcPending();
        setForeignQcPending(inspection);
        if (inspection.pending || inspection.corruption) setQr("");
      }
    }
    window.addEventListener("storage", syncAcrossTabs);
    return () => window.removeEventListener("storage", syncAcrossTabs);
  }, []);

  useEffect(() => {
    const data = bootstrap.data;
    if (!data) return;
    const active = sessions.data?.items.find((item) => !item.ended_at) ?? null;
    setSession((current) => current ?? active);
    setRowId((value) => value || data.rows[0]?.id || "");
  }, [bootstrap.data, sessions.data]);

  const workstations = useMemo(() => bootstrap.data?.workstations.filter((item) => item.row_id === rowId) ?? [], [bootstrap.data, rowId]);
  const steps = useMemo(() => {
    const row = bootstrap.data?.rows.find((item) => item.id === rowId);
    return bootstrap.data?.route_steps.filter((item) => item.row_id === rowId || (item.row_id === null && row?.category === "ASSEMBLY")) ?? [];
  }, [bootstrap.data, rowId]);

  useEffect(() => {
    if (!workstations.some((item) => item.id === workstationId)) setWorkstationId(workstations[0]?.id ?? "");
    if (!steps.some((item) => item.id === routeStepId)) setRouteStepId(steps[0]?.id ?? "");
  }, [workstations, steps, workstationId, routeStepId]);

  useEffect(() => {
    if (!pending || !user || activeSubmissionIdRef.current === pending.eventId) return;
    let active = true;
    setBusy(true);
    api.get<OperationEventResult>(`/operation-events/${pending.eventId}/status`)
      .then((response) => {
        if (!active || activeSubmissionIdRef.current === pending.eventId) return;
        setResult(response);
        if (isServerAcknowledgement(response)) {
          clearPendingScan(pending.eventId);
          setPending(null);
          if (isWorkerView) void activity.reload();
        }
      })
      .catch((caught) => {
        if (!active || (caught instanceof ApiError && caught.status === 404)) return;
        setError(caught instanceof Error ? caught.message : "Не удалось восстановить состояние скана");
      })
      .finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [pending?.eventId, user?.id, isWorkerView, activity.reload]);

  if (!user || !canAccess(user, "scan")) return <AccessDenied />;
  if (bootstrap.loading) return <div className="page"><LoadingState rows={7} /></div>;
  if (bootstrap.error) return <div className="page"><ErrorState message={bootstrap.error.message} onRetry={() => void bootstrap.reload()} /></div>;
  if (!bootstrap.data?.active_shift) return <div className="page"><PageHeader title="Сканирование" /><ErrorState title="Активная смена не назначена" message="Начать рабочую сессию пока нельзя." /></div>;

  async function openSession(event: React.FormEvent) {
    event.preventDefault();
    if (!bootstrap.data?.active_shift || pending || corruption || foreignQcPending.pending || foreignQcPending.corruption) return;
    setBusy(true); setError(null);
    try {
      const next = await api.post<WorkSession>("/work-sessions", { shift_id: bootstrap.data.active_shift.id, row_id: rowId, workstation_id: workstationId, route_step_id: routeStepId });
      setSession(next);
      queueMicrotask(() => inputRef.current?.focus());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось открыть рабочую сессию");
    } finally { setBusy(false); }
  }

  async function closeSession() {
    if (!session || pending || corruption || foreignQcPending.pending || foreignQcPending.corruption) return;
    setBusy(true); setError(null);
    try { await api.delete<void>(`/work-sessions/${session.id}`); setSession(null); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Не удалось завершить сессию"); }
    finally { setBusy(false); }
  }

  async function withSubmitLock(task: () => Promise<void>) {
    let acquired = false;
    if (!("locks" in navigator)) {
      setError("Этот браузер не поддерживает безопасную блокировку между вкладками. Закройте другие вкладки и используйте актуальный Chrome/Edge.");
      return;
    }
    await navigator.locks.request("kpd-demo.operation-submit", { ifAvailable: true }, async (lock) => {
      if (!lock) return;
      acquired = true;
      await task();
    });
    if (!acquired) setError("Скан уже отправляется в другой вкладке. Дождитесь ответа сервера.");
  }

  async function retryPendingSafely(current: PendingScan) {
    const qcInspection = inspectQcPending();
    setForeignQcPending(qcInspection);
    if (qcInspection.pending || qcInspection.corruption) {
      setError("Проверка ОТК ещё не подтверждена. Сначала завершите её под исходной учётной записью.");
      return;
    }
    await sendPendingUnlocked(current);
  }

  async function sendPendingUnlocked(current: PendingScan) {
    if (!user) return;
    if (current.actorId !== user.id) {
      setError(`Скан создан пользователем ${current.actorName}. Войдите под исходной ролью или передайте событие бригадиру.`);
      return;
    }
    activeSubmissionIdRef.current = current.eventId;
    setBusy(true); setError(null); setResult(null);
    try {
      const response = await api.post<OperationEventResult>("/operation-events", current.body);
      setResult(response);
      if (isServerAcknowledgement(response)) {
        clearPendingScan(current.eventId);
        setPending(null); setCorruption(null);
        setQr("");
        if (isWorkerView) await activity.reload();
        queueMicrotask(() => inputRef.current?.focus());
      }
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Нет подтверждения сервера";
      if (caught instanceof ApiError && caught.submission?.terminal && caught.submission.event_id === current.eventId) {
        clearPendingScan(current.eventId);
        setPending(null);
        setResult({
          status: caught.submission.status,
          code: caught.submission.code ?? caught.code,
          message: caught.submission.message ?? caught.message,
          accepted: false,
          terminal: true,
          retryable: false,
          next_steps: caught.submission.next_steps,
        });
        setError(`${message} Исправьте QR или рабочий контекст и повторите сканирование.`);
        return;
      }
      annotatePendingError(message);
      setPending(readPendingScan());
      setError(message);
    } finally {
      if (activeSubmissionIdRef.current === current.eventId) activeSubmissionIdRef.current = null;
      setBusy(false);
    }
  }

  async function submitScan(event: React.FormEvent) {
    event.preventDefault();
    if (!user || !session || pending || corruption || busy || !qr.trim()) return;
    await withSubmitLock(async () => {
      const currentInspection = inspectPendingScan();
      if (currentInspection.pending || currentInspection.corruption) {
        setPending(currentInspection.pending); setCorruption(currentInspection.corruption);
        setError("В другой вкладке уже создан неподтверждённый скан.");
        return;
      }
      const qcInspection = inspectQcPending();
      setForeignQcPending(qcInspection);
      if (qcInspection.pending || qcInspection.corruption) {
        setError("Проверка ОТК в другой вкладке ещё не подтверждена. Завершите её перед новым сканом.");
        return;
      }
      const verifiedRework = await checkReworkAuthorization(qr.trim());
      if (attemptType === "REWORK" && !verifiedRework) {
        setError("Для этого QR и текущей операции нет открытого разрешения на переделку.");
        return;
      }
      const selectedAttempt = verifiedRework ? (authorizedRework ? attemptType : "REWORK") : "PRIMARY";
      const body: OperationEventBody = {
        event_id: crypto.randomUUID(),
        work_session_id: session.id,
        subject_qr: qr.trim(),
        event_type: "COMPLETE",
        attempt_type: selectedAttempt,
        occurred_at_device: new Date().toISOString(),
      };
      const durable = createPendingScan(user.id, user.display_name, body);
      setPending(durable);
      await sendPendingUnlocked(durable);
      void reworks.reload();
    });
  }

  async function checkReworkAuthorization(value: string) {
    if (!value.trim() || !session) { setAuthorizedRework(null); setAttemptType("PRIMARY"); return null; }
    try {
      const entity = await api.get<TrackedEntity>(`/entities/by-qr/${encodeURIComponent(value.trim())}`);
      const row = bootstrap.data?.rows.find((item) => item.id === session.row_id);
      const orders = reworks.data ?? await api.get<ListResponse<ReworkOrder>>("/rework-orders");
      const match = orders.items.find((item) => item.entity_id === entity.id && (
        (item.status === "OPEN" && item.requested_route_step_id === session.route_step_id) ||
        (item.status === "READY_FOR_QC" && row?.category === "QC")
      )) ?? null;
      setAuthorizedRework(match);
      setAttemptType(match ? "REWORK" : "PRIMARY");
      return match;
    } catch {
      setAuthorizedRework(null); setAttemptType("PRIMARY"); return null;
    }
  }

  async function resolvePending(action: "RETRY_OWNER" | "CANCEL") {
    if (!pending) return;
    setBusy(true); setError(null);
    try {
      const response = await api.post<OperationEventResult>(`/operation-events/${pending.eventId}/resolve`, { action, reason: action === "CANCEL" ? "Разрешено бригадиром в демо-интерфейсе" : "Повтор от исходного владельца" });
      setResult(response);
      if (isServerAcknowledgement(response)) { clearPendingScan(pending.eventId); setPending(null); setCorruption(null); if (isWorkerView) await activity.reload(); }
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Не удалось разрешить pending scan"); }
    finally { setBusy(false); }
  }

  async function resolveCorruption() {
    if (!corruption || !corruptionReason.trim()) return;
    setBusy(true); setError(null);
    try {
      const bytes = new TextEncoder().encode(corruption.raw);
      const digest = await crypto.subtle.digest("SHA-256", bytes);
      const fingerprint = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
      const response = await api.post<OperationEventResult>("/operation-events/resolve-local-corruption", { reason: corruptionReason.trim(), fingerprint });
      if (!isServerAcknowledgement(response)) throw new Error("Backend не подтвердил разрешение повреждённой записи.");
      clearCorruptedPending(corruption.raw);
      setCorruption(null); setPending(null); setCorruptionReason(""); setResult(response);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Не удалось разрешить повреждённую запись"); }
    finally { setBusy(false); }
  }

  const selectedRow = bootstrap.data.rows.find((item) => item.id === session?.row_id);
  const selectedStation = bootstrap.data.workstations.find((item) => item.id === session?.workstation_id);
  const selectedStep = bootstrap.data.route_steps.find((item) => item.id === session?.route_step_id);
  const actorMismatch = Boolean(pending && pending.actorId !== user.id);
  const canResolve = user.capabilities.includes("resolve_pending") || user.capabilities.includes("admin");
  const scanBlocked = Boolean(pending || corruption || foreignQcPending.pending || foreignQcPending.corruption);

  if (isWorkerView) {
    const primaryCount = activity.error || !activity.data?.shift ? null : activity.data.primary_completed;
    const reworkCount = activity.error || !activity.data?.shift ? null : activity.data.rework_completed;
    return (
      <div className="page worker-scan-page">
        <h1 className="sr-only">Сканирование QR</h1>
        <header className="worker-shift-heading">
          <div><span>Смена</span><strong>{bootstrap.data.active_shift.code}</strong></div>
          <p>Сканируйте QR после завершения операции.</p>
        </header>

        {error && <div className="inline-alert inline-alert--danger" role="alert"><AlertTriangle /><div><strong>Операция не завершена</strong><p>{error}</p></div></div>}

        {corruption && <section className="pending-lock pending-lock--corrupt" aria-live="assertive">
          <span className="pending-lock__icon"><AlertTriangle /></span>
          <div><StatusBadge tone="danger">Ошибка восстановления</StatusBadge><h2>Новые операции заблокированы</h2><p>Сохранённая операция повреждена и не удалена. Не сканируйте следующий код: позовите бригадира.</p></div>
          <div className="pending-lock__actions"><StatusBadge tone="danger">Нужен бригадир</StatusBadge></div>
        </section>}

        {pending && <section className="pending-lock" aria-live="assertive">
          <span className="pending-lock__icon"><CircleStop /></span>
          <div><StatusBadge tone="warning">Не подтверждено сервером</StatusBadge><h2>Операция ещё не подтверждена</h2><p>QR {pending.body.subject_qr}. Повторите отправку после восстановления связи; следующий код пока заблокирован.</p></div>
          <div className="pending-lock__actions">
            {!actorMismatch && <button className="button button--primary" disabled={busy} type="button" onClick={() => void withSubmitLock(() => retryPendingSafely(pending))}><RefreshCw size={16} />Повторить отправку</button>}
            {actorMismatch && <StatusBadge tone="danger"><UserRound size={13} />Нужен исходный пользователь</StatusBadge>}
          </div>
        </section>}

        {(foreignQcPending.pending || foreignQcPending.corruption) && <section className="pending-lock" aria-live="assertive">
          <span className="pending-lock__icon"><CircleStop /></span>
          <div><StatusBadge tone="warning">Другое действие не завершено</StatusBadge><h2>Проверка ОТК ожидает подтверждения</h2><p>Завершите или разрешите её под исходной учётной записью. Новый скан пока заблокирован.</p></div>
          <div className="pending-lock__actions"><StatusBadge tone="danger">Нужен исходный экран ОТК</StatusBadge></div>
        </section>}

        {!session ? <section className="workspace-section worker-session-setup">
          <SectionHeader title="Выберите рабочее место" description="Контекст нужен серверу для проверки ряда, операции и назначения." />
          <form className="session-form" onSubmit={openSession}>
            <label className="field"><span>Ряд</span><select value={rowId} onChange={(event) => setRowId(event.target.value)}>{bootstrap.data.rows.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
            <label className="field"><span>Рабочее место</span><select value={workstationId} onChange={(event) => setWorkstationId(event.target.value)}>{workstations.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
            <label className="field"><span>Операция</span><select value={routeStepId} onChange={(event) => setRouteStepId(event.target.value)}>{steps.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
            <button className="button button--primary" disabled={busy || !rowId || !workstationId || !routeStepId || scanBlocked} type="submit"><LogIn size={16} />Начать работу</button>
          </form>
        </section> : <>
          <section className="worker-scan-workspace">
            <div className="worker-operation-context">
              <div><span>Ряд</span><strong>{selectedRow?.name ?? activity.data?.context?.row.name ?? "—"}</strong></div>
              <div><span>Операция</span><strong>{selectedStep?.name ?? activity.data?.context?.route_step.name ?? "—"}</strong></div>
              <details><summary>Рабочее место</summary><p>{selectedStation?.name ?? "Не указано"}</p><button className="text-button" type="button" disabled={busy || scanBlocked} onClick={() => void closeSession()}>Сменить рабочее место</button></details>
            </div>

            <div className="worker-scan-main">
              <form className="worker-scan-form" onSubmit={submitScan}>
                <label htmlFor="qr-input">QR детали, узла или изделия</label>
                <span className="sr-only" id="worker-scan-hint">После ввода QR нажмите Enter.</span>
                <div className="scan-input-wrap worker-scan-input"><ScanLine aria-hidden="true" /><input ref={inputRef} id="qr-input" aria-describedby="worker-scan-hint" value={qr} disabled={busy || scanBlocked} onChange={(event) => { setQr(event.target.value); setAuthorizedRework(null); setAttemptType("PRIMARY"); }} onBlur={() => void checkReworkAuthorization(qr)} placeholder="Отсканируйте QR" autoComplete="off" autoFocus /><button className="button button--primary" disabled={busy || scanBlocked || !qr.trim()} type="submit">{busy ? <LoaderCircle className="spin" /> : <Keyboard />}Подтвердить</button></div>
                {authorizedRework && <fieldset className="attempt-choice"><legend>Разрешённый повтор</legend><label><input type="radio" name="attempt-type" value="PRIMARY" checked={attemptType === "PRIMARY"} onChange={() => setAttemptType("PRIMARY")} />Первичная операция</label><label><input type="radio" name="attempt-type" value="REWORK" checked={attemptType === "REWORK"} onChange={() => setAttemptType("REWORK")} />Переделка</label><p>Переделка считается отдельно и не увеличивает первичные операции.</p></fieldset>}
              </form>

              <aside className="worker-count" aria-live="polite">
                <span>Выполнено за смену</span>
                <strong data-testid="worker-primary-count">{activity.loading ? "…" : primaryCount ?? "—"}</strong>
                <p>первичных операций</p>
                <small>Переделка: <b data-testid="worker-rework-count">{activity.loading ? "…" : reworkCount ?? "—"}</b> операций</small>
              </aside>
            </div>

            {result && <div className="worker-current-result" data-status={result.status} role="status">
              {result.status === "ACCEPTED" && !result.duplicate ? <CheckCircle2 aria-hidden="true" /> : result.duplicate ? <RotateCcw aria-hidden="true" /> : <AlertTriangle aria-hidden="true" />}
              <div><StatusBadge tone={toneForStatus(result.status)}>{result.duplicate ? "Уже учтено" : humanize(result.status)}</StatusBadge><strong>{result.message ?? (result.status === "ACCEPTED" ? "Операция принята" : "Ответ сервера получен")}</strong></div>
            </div>}
          </section>

          <section className="workspace-section worker-history" aria-labelledby="worker-history-title">
            <div className="section-header"><div><h2 id="worker-history-title">Последние сканы</h2><p>Сохранённые операции за смену · время сервера</p></div><button className="icon-button" type="button" aria-label="Обновить последние операции" disabled={activity.loading} onClick={() => void activity.reload()}><RefreshCw /></button></div>
            {activity.loading ? <LoadingState rows={4} label="Загружаем последние операции" /> : activity.error ? <ErrorState title="Не удалось обновить личный итог" message={activity.error.message} onRetry={() => void activity.reload()} /> : !activity.data?.shift ? <div className="worker-history-empty"><Clock3 /><div><strong>Нет активной смены</strong><p>Личный итог и история появятся после открытия смены.</p></div></div> : activity.data.recent_events.length === 0 ? <div className="worker-history-empty"><ScanLine /><div><strong>Сканов пока нет</strong><p>После серверного подтверждения операция появится здесь.</p></div></div> : <ol className="worker-history-list">
              {activity.data.recent_events.map((event) => {
                const presentation = workerEventPresentation(event);
                return <li key={event.event_id} data-event-id={event.event_id}><time dateTime={event.server_received_at}>{formatDateTime(event.server_received_at)}</time><code>{event.subject_qr}</code><span>{event.row?.name ?? "Ряд не указан"} · {event.route_step?.name ?? "Операция не указана"}</span><StatusBadge compact tone={presentation.tone}>{presentation.label}</StatusBadge></li>;
              })}
            </ol>}
          </section>
        </>}
      </div>
    );
  }

  return (
    <div className="page scan-page">
      <PageHeader title="QR-сканирование" description="Событие фиксируется только после однозначного подтверждения сервера." meta={<span className="demo-marker">ДЕМО</span>} actions={<Link className="button button--secondary" to="/scan/demo-codes"><QrCode size={16} />Демо QR-коды</Link>} />

      {error && <div className="inline-alert inline-alert--danger" role="alert"><AlertTriangle /><div><strong>Действие не завершено</strong><p>{error}</p></div></div>}

      {corruption && <section className="pending-lock pending-lock--corrupt" aria-live="assertive">
        <span className="pending-lock__icon"><AlertTriangle /></span>
        <div><StatusBadge tone="danger">Ошибка восстановления</StatusBadge><h2>Новые операции заблокированы</h2><p>Сохранённая операция повреждена и не удалена. Не сканируйте следующий код: позовите бригадира для аудируемого разрешения.</p><details><summary>Технические сведения</summary><p>{corruption.message}</p><code>{corruption.raw.slice(0, 480)}</code></details></div>
        <div className="pending-lock__actions">{canResolve ? <><label className="field"><span>Причина разрешения</span><input value={corruptionReason} onChange={(event) => setCorruptionReason(event.target.value)} placeholder="Что произошло" /></label><button className="button button--primary" type="button" disabled={busy || !corruptionReason.trim()} onClick={() => void resolveCorruption()}>Зафиксировать и очистить</button></> : <StatusBadge tone="danger">Нужен бригадир</StatusBadge>}</div>
      </section>}

      {pending && <section className="pending-lock" aria-live="assertive">
        <span className="pending-lock__icon"><CircleStop /></span>
        <div><StatusBadge tone="warning">Не подтверждено сервером</StatusBadge><h2>Операция ещё не подтверждена</h2><p>Повторите отправку после восстановления связи. Следующий код пока недоступен.</p><dl><div><dt>Автор</dt><dd>{pending.actorName}</dd></div><div><dt>QR</dt><dd>{pending.body.subject_qr}</dd></div><div><dt>Создан</dt><dd>{formatDateTime(pending.createdAt)}</dd></div></dl><details><summary>Технические сведения</summary><p>Сохранён исходный UUID и неизменяемый контекст запроса.</p><code>{pending.eventId}</code></details></div>
        <div className="pending-lock__actions">
          {!actorMismatch && <button className="button button--primary" disabled={busy} type="button" onClick={() => void withSubmitLock(() => retryPendingSafely(pending))}><RefreshCw size={16} />Повторить отправку</button>}
          {actorMismatch && <StatusBadge tone="danger"><UserRound size={13} />Нужен исходный пользователь</StatusBadge>}
          {canResolve && <button className="button button--secondary" disabled={busy} type="button" onClick={() => void resolvePending("CANCEL")}>Разрешить бригадиром</button>}
        </div>
      </section>}

      {(foreignQcPending.pending || foreignQcPending.corruption) && <section className="pending-lock" aria-live="assertive">
        <span className="pending-lock__icon"><CircleStop /></span>
        <div><StatusBadge tone="warning">Другое действие не завершено</StatusBadge><h2>Проверка ОТК ожидает подтверждения</h2><p>Завершите или разрешите её на экране ОТК. Сканирование операций заблокировано.</p></div>
        <div className="pending-lock__actions"><StatusBadge tone="danger">Нужен исходный экран ОТК</StatusBadge></div>
      </section>}

      <section className="scan-layout">
        <div className="workspace-section scan-workspace">
          <SectionHeader title="Рабочее место" description="Сканер вводит код как клавиатура и завершает ввод клавишей Enter." action={session && !pending ? <button className="button button--quiet" type="button" onClick={() => void closeSession()}>Завершить сессию</button> : undefined} />
          {!session ? (
            <form className="session-form" onSubmit={openSession}>
              <label className="field"><span>Ряд</span><select value={rowId} onChange={(event) => setRowId(event.target.value)}>{bootstrap.data.rows.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
              <label className="field"><span>Рабочее место</span><select value={workstationId} onChange={(event) => setWorkstationId(event.target.value)}>{workstations.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
              <label className="field"><span>Операция</span><select value={routeStepId} onChange={(event) => setRouteStepId(event.target.value)}>{steps.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
              <button className="button button--primary" disabled={busy || !rowId || !workstationId || !routeStepId || scanBlocked} type="submit"><LogIn size={16} />Начать сессию</button>
            </form>
          ) : (
            <>
              <div className="session-context"><div><span>Работник</span><strong>{user.display_name}</strong></div><div><span>Смена</span><strong>{bootstrap.data.active_shift.code}</strong></div><div><span>Ряд</span><strong>{selectedRow?.name ?? "—"}</strong></div><div><span>Место</span><strong>{selectedStation?.name ?? "—"}</strong></div><div><span>Операция</span><strong>{selectedStep?.name ?? "—"}</strong></div></div>
              <form className="scan-form" onSubmit={submitScan}>
                <label htmlFor="qr-input">QR детали, WIP или изделия</label>
                <div className="scan-input-wrap"><ScanLine aria-hidden="true" /><input ref={inputRef} id="qr-input" value={qr} disabled={busy || scanBlocked} onChange={(event) => { setQr(event.target.value); setAuthorizedRework(null); setAttemptType("PRIMARY"); }} onBlur={() => void checkReworkAuthorization(qr)} placeholder="Отсканируйте код и нажмите Enter" autoComplete="off" autoFocus /><button className="button button--primary" disabled={busy || scanBlocked || !qr.trim()} type="submit">{busy ? <LoaderCircle className="spin" /> : <Keyboard />}Подтвердить</button></div>
                {authorizedRework && <fieldset className="attempt-choice"><legend>Разрешённый режим операции</legend><label><input type="radio" name="attempt-type" value="PRIMARY" checked={attemptType === "PRIMARY"} onChange={() => setAttemptType("PRIMARY")} />Первичная операция</label><label><input type="radio" name="attempt-type" value="REWORK" checked={attemptType === "REWORK"} onChange={() => setAttemptType("REWORK")} />Переделка или повторный контроль</label><p>Разрешение подтверждено серверным заказом на переделку. Номер попытки определяет backend.</p></fieldset>}
                <p>Новый код нельзя отправить, пока предыдущий не получил ответ сервера.</p>
              </form>
              <div className="sample-codes"><span>Доступные демо-коды</span><div>{bootstrap.data.sample_qr.map((sample) => <button key={sample} type="button" disabled={busy || scanBlocked} onClick={() => { setQr(sample); void checkReworkAuthorization(sample); inputRef.current?.focus(); }}><strong>Синтетический QR</strong><code>{sample}</code></button>)}</div></div>
            </>
          )}
        </div>

        <aside className="workspace-section scan-result" aria-live="polite">
          <SectionHeader title="Последний ответ" />
          {!result ? <div className="scan-result__empty"><ScanLine /><p>После скана здесь появятся серверный статус, объект и следующий разрешённый шаг.</p></div> : <div className="scan-result__content" data-status={result.status}>
            {result.status === "ACCEPTED" && !result.duplicate ? <CheckCircle2 aria-hidden="true" /> : result.duplicate ? <RotateCcw aria-hidden="true" /> : <AlertTriangle aria-hidden="true" />}
            <StatusBadge tone={toneForStatus(result.status)}>{humanize(result.status)}</StatusBadge>
            <h3>{result.message ?? (result.status === "ACCEPTED" ? "Операция принята сервером" : "Ответ сервера получен")}</h3>
            <dl><div><dt>Код ответа</dt><dd>{result.code}</dd></div><div><dt>Принято сервером</dt><dd>{formatDateTime(result.server_received_at)}</dd></div>{result.entity && <div><dt>Объект</dt><dd>{result.entity.qr_code}</dd></div>}</dl>
            {result.next_steps.length > 0 && <div className="next-steps"><strong>Следующие шаги</strong><ul>{result.next_steps.map((step) => <li key={step}>{step}</li>)}</ul></div>}
          </div>}
        </aside>
      </section>
    </div>
  );
}

