import { AlertTriangle, Check, CheckCircle2, CircleStop, Clock3, Keyboard, LoaderCircle, RefreshCw, RotateCcw, ScanLine, UserRound, Wrench, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import { inspectPendingScan, PENDING_KEY } from "../api/pending";
import { annotateQcPendingError, clearQcPending, createQcPending, inspectQcPending, QC_PENDING_KEY, readQcPending, type PendingQcInspection } from "../api/qcPending";
import type { Bootstrap, QcDefectReasonCatalog, QcInspectionBody, QcInspectionResult, QcRecentInspection, QcShiftActivity, ReworkOrder, WorkSession } from "../api/types";
import { useAuth } from "../app/AuthContext";
import { formatDateTime } from "../app/format";
import { useResource } from "../app/useResource";
import { ErrorState, LoadingState } from "../components/PageState";
import { SectionHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";

const SUBMIT_LOCK = "kpd-demo.operation-submit";

function decisionLabel(item: Pick<QcRecentInspection, "decision" | "mode">) {
  if (item.mode === "REINSPECTION") return item.decision === "ACCEPT" ? "Годен · повторно" : "Брак · повторно";
  return item.decision === "ACCEPT" ? "Годен" : "Брак";
}

function decisionPresentation(item: Pick<QcRecentInspection, "decision" | "mode" | "corrected" | "display_status">) {
  if (item.corrected || item.display_status === "CORRECTED") return { label: "Исправлено", tone: "warning" as const };
  return { label: decisionLabel(item), tone: item.decision === "ACCEPT" ? "success" as const : "warning" as const };
}

export function QcWorkspacePage() {
  const { user } = useAuth();
  const bootstrap = useResource(() => api.get<Bootstrap>("/bootstrap"), []);
  const activity = useResource(() => api.get<QcShiftActivity>("/me/qc-shift-activity?limit=10"), []);
  const reasons = useResource(() => api.get<QcDefectReasonCatalog>("/qc-defect-reasons"), []);
  const initialPending = useMemo(() => inspectQcPending(), []);
  const [pending, setPending] = useState<PendingQcInspection | null>(initialPending.pending);
  const [corruption, setCorruption] = useState(initialPending.corruption);
  const [foreignWorkerPending, setForeignWorkerPending] = useState(() => inspectPendingScan());
  const [qr, setQr] = useState("");
  const [decision, setDecision] = useState<"ACCEPT" | "REJECT" | null>(null);
  const [defectCode, setDefectCode] = useState("");
  const [result, setResult] = useState<QcInspectionResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [setupRow, setSetupRow] = useState("");
  const [setupStation, setSetupStation] = useState("");
  const [setupStep, setSetupStep] = useState("");
  const [reworkStep, setReworkStep] = useState("");
  const [reworkDecisionId, setReworkDecisionId] = useState("");
  const [reworkReason, setReworkReason] = useState("");
  const [reworkMessage, setReworkMessage] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const activeSubmissionIdRef = useRef<string | null>(null);

  const qcRows = useMemo(() => bootstrap.data?.rows.filter((row) => row.category === "QC") ?? [], [bootstrap.data]);
  const qcStations = useMemo(() => bootstrap.data?.workstations.filter((station) => station.row_id === setupRow) ?? [], [bootstrap.data, setupRow]);
  const qcSteps = useMemo(() => bootstrap.data?.route_steps.filter((step) => step.row_id === setupRow) ?? [], [bootstrap.data, setupRow]);
  const reworkSteps = useMemo(() => bootstrap.data?.route_steps.filter((step) => {
    const row = bootstrap.data?.rows.find((candidate) => candidate.id === step.row_id);
    return step.allows_rework && (step.row_id === null || row?.category === "ASSEMBLY" || row?.category === "SOLDER");
  }) ?? [], [bootstrap.data]);
  const reworkCandidates = useMemo(() => {
    const candidates = [
      ...(result?.inspection?.decision === "REJECT" ? [result.inspection] : []),
      ...(activity.data?.recent_inspections.filter((item) => item.decision === "REJECT" && !item.corrected && item.display_status !== "CORRECTED") ?? []),
    ];
    const effective = candidates.filter((item) => item.decision === "REJECT" && !item.corrected && item.display_status !== "CORRECTED");
    return effective.filter((item, index) => effective.findIndex((candidate) => candidate.decision_id === item.decision_id) === index);
  }, [activity.data?.recent_inspections, result?.inspection]);
  const selectedRework = reworkCandidates.find((item) => item.decision_id === reworkDecisionId) ?? reworkCandidates[0] ?? null;

  useEffect(() => {
    const row = qcRows[0];
    if (!setupRow && row) setSetupRow(row.id);
  }, [qcRows, setupRow]);

  useEffect(() => {
    if (!qcStations.some((item) => item.id === setupStation)) setSetupStation(qcStations[0]?.id ?? "");
    if (!qcSteps.some((item) => item.id === setupStep)) setSetupStep(qcSteps[0]?.id ?? "");
  }, [qcStations, qcSteps, setupStation, setupStep]);

  useEffect(() => {
    function syncAcrossTabs(event: StorageEvent) {
      if (event.key === QC_PENDING_KEY) {
        const inspection = inspectQcPending();
        setPending(inspection.pending);
        setCorruption(inspection.corruption);
        if (inspection.pending || inspection.corruption) setQr("");
      }
      if (event.key === PENDING_KEY) {
        const inspection = inspectPendingScan();
        setForeignWorkerPending(inspection);
        if (inspection.pending || inspection.corruption) setQr("");
      }
    }
    window.addEventListener("storage", syncAcrossTabs);
    return () => window.removeEventListener("storage", syncAcrossTabs);
  }, []);

  useEffect(() => {
    if (!pending || !user || pending.actorId !== user.id || activeSubmissionIdRef.current === pending.inspectionId) return;
    let active = true;
    setBusy(true);
    api.get<QcInspectionResult>(`/qc-inspections/${pending.inspectionId}/status`)
      .then(async (response) => {
        if (!active || activeSubmissionIdRef.current === pending.inspectionId) return;
        setResult(response);
        if (response.terminal && response.inspection_id === pending.inspectionId) {
          clearQcPending(pending.inspectionId);
          setPending(null);
          await activity.reload();
        }
      })
      .catch((caught) => {
        if (!active || (caught instanceof ApiError && caught.status === 404)) return;
        setError(caught instanceof Error ? caught.message : "Не удалось восстановить проверку");
      })
      .finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [pending?.inspectionId, user?.id, activity.reload]);

  async function withSubmitLock(task: () => Promise<void>) {
    let acquired = false;
    if (!("locks" in navigator)) {
      setError("Безопасная блокировка между вкладками недоступна. Используйте актуальный Chrome или Edge.");
      return;
    }
    try {
      await navigator.locks.request(SUBMIT_LOCK, { ifAvailable: true }, async (lock) => {
        if (!lock) return;
        acquired = true;
        await task();
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Не удалось безопасно сохранить проверку.");
      return;
    }
    if (!acquired) setError("Другое действие уже отправляется. Дождитесь ответа сервера.");
  }

  async function sendPendingUnlocked(current: PendingQcInspection) {
    if (!user) return;
    if (current.actorId !== user.id) {
      setError(`Проверку начал пользователь ${current.actorName}. Войдите под исходной учётной записью.`);
      return;
    }
    activeSubmissionIdRef.current = current.inspectionId;
    setBusy(true); setError(null); setResult(null);
    try {
      const response = await api.post<QcInspectionResult>("/qc-inspections", current.body);
      setResult(response);
      if (response.terminal && response.inspection_id === current.inspectionId) {
        clearQcPending(current.inspectionId);
        setPending(null); setCorruption(null); setQr(""); setDecision(null); setDefectCode("");
        await activity.reload();
        queueMicrotask(() => inputRef.current?.focus());
      }
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Нет подтверждения сервера";
      if (caught instanceof ApiError && caught.submission?.terminal && caught.submission.inspection_id === current.inspectionId) {
        clearQcPending(current.inspectionId);
        setPending(null);
        setResult({ inspection_id: current.inspectionId, status: "REJECTED_TERMINAL", accepted: false, terminal: true, retryable: false, duplicate: false, message, next_steps: caught.submission.next_steps, inspection: null });
        setError(`${message} Исправьте QR или рабочий контекст и повторите проверку.`);
        queueMicrotask(() => inputRef.current?.focus());
        return;
      }
      annotateQcPendingError(message);
      setPending(readQcPending());
      setError(message);
    } finally {
      if (activeSubmissionIdRef.current === current.inspectionId) activeSubmissionIdRef.current = null;
      setBusy(false);
    }
  }

  async function retryPendingSafely(current: PendingQcInspection) {
    const operationInspection = inspectPendingScan();
    setForeignWorkerPending(operationInspection);
    if (operationInspection.pending || operationInspection.corruption) {
      setError("Операция в другом рабочем экране ещё не подтверждена.");
      return;
    }
    await sendPendingUnlocked(current);
  }

  async function submitDecision(nextDecision: "ACCEPT" | "REJECT") {
    if (!user || !activity.data?.context || busy || pending || corruption || foreignWorkerPending.pending || foreignWorkerPending.corruption || !qr.trim()) return;
    const workSessionId = activity.data.context.work_session_id;
    if (nextDecision === "REJECT" && !defectCode) {
      setDecision("REJECT");
      setError("Выберите причину брака.");
      return;
    }
    await withSubmitLock(async () => {
      const operationInspection = inspectPendingScan();
      setForeignWorkerPending(operationInspection);
      if (operationInspection.pending || operationInspection.corruption) {
        setError("Операция в другом рабочем экране ещё не подтверждена.");
        return;
      }
      const qcInspection = inspectQcPending();
      if (qcInspection.pending || qcInspection.corruption) {
        setPending(qcInspection.pending); setCorruption(qcInspection.corruption);
        setError("В другой вкладке уже создана неподтверждённая проверка.");
        return;
      }
      const body: QcInspectionBody = {
        inspection_id: crypto.randomUUID(),
        work_session_id: workSessionId,
        subject_qr: qr.trim(),
        decision: nextDecision,
        defect_code: nextDecision === "REJECT" ? defectCode : null,
        occurred_at_device: new Date().toISOString(),
      };
      const durable = createQcPending(user.id, user.display_name, body);
      setPending(durable);
      await sendPendingUnlocked(durable);
    });
  }

  async function openSession(event: React.FormEvent) {
    event.preventDefault();
    if (!bootstrap.data?.active_shift || !setupRow || !setupStation || !setupStep) return;
    setBusy(true); setError(null);
    try {
      await api.post<WorkSession>("/work-sessions", { shift_id: bootstrap.data.active_shift.id, row_id: setupRow, workstation_id: setupStation, route_step_id: setupStep });
      await activity.reload();
      queueMicrotask(() => inputRef.current?.focus());
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Не удалось открыть рабочую сессию ОТК"); }
    finally { setBusy(false); }
  }

  async function openRework() {
    if (!selectedRework || !reworkStep || !reworkReason.trim()) return;
    setBusy(true); setError(null); setReworkMessage(null);
    try {
      await api.post<ReworkOrder>("/rework-orders", {
        request_id: crypto.randomUUID(), entity_qr: selectedRework.subject_qr,
        quality_decision_id: selectedRework.decision_id,
        requested_route_step_id: reworkStep, reason: reworkReason.trim(),
      });
      setReworkMessage("Переделка открыта отдельно от результата проверки.");
      setReworkReason(""); setReworkStep("");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Не удалось открыть переделку"); }
    finally { setBusy(false); }
  }

  if (bootstrap.loading || activity.loading && !activity.data) return <div className="page qc-workspace-page"><LoadingState rows={6} label="Загружаем рабочее место ОТК" /></div>;
  if (bootstrap.error) return <div className="page qc-workspace-page"><ErrorState message={bootstrap.error.message} onRetry={() => void bootstrap.reload()} /></div>;
  if (!bootstrap.data?.active_shift) return <div className="page qc-workspace-page"><ErrorState title="Нет активной смены" message="Проверки станут доступны после открытия смены." /></div>;

  const actorMismatch = Boolean(pending && pending.actorId !== user?.id);
  const blocked = Boolean(busy || pending || corruption || foreignWorkerPending.pending || foreignWorkerPending.corruption);
  const checked = activity.error || !activity.data?.shift ? null : activity.data.checked_count;
  const repeated = activity.error || !activity.data?.shift ? null : activity.data.reinspection_count;

  return <div className="page worker-scan-page qc-workspace-page">
    <h1 className="sr-only">Контроль ОТК</h1>
    <header className="worker-shift-heading"><div><span>Смена</span><strong>{bootstrap.data.active_shift.code}</strong></div><p>Отсканируйте QR и зафиксируйте результат.</p></header>

    {error && <div className="inline-alert inline-alert--danger" role="alert"><AlertTriangle /><div><strong>Проверка не завершена</strong><p>{error}</p></div></div>}

    {corruption && <section className="pending-lock pending-lock--corrupt" aria-live="assertive"><span className="pending-lock__icon"><AlertTriangle /></span><div><StatusBadge tone="danger">Ошибка восстановления</StatusBadge><h2>Новые проверки заблокированы</h2><p>Локальная запись повреждена и не удалена. Позовите бригадира для аудируемого разрешения.</p></div><div className="pending-lock__actions"><StatusBadge tone="danger">Нужен бригадир</StatusBadge></div></section>}

    {pending && <section className="pending-lock" aria-live="assertive"><span className="pending-lock__icon"><CircleStop /></span><div><StatusBadge tone="warning">Не подтверждено сервером</StatusBadge><h2>Проверка ещё не подтверждена</h2><p>QR {pending.body.subject_qr}. Следующая проверка заблокирована.</p></div><div className="pending-lock__actions">{!actorMismatch ? <button className="button button--primary" disabled={busy} type="button" onClick={() => void withSubmitLock(() => retryPendingSafely(pending))}><RefreshCw size={16} />Повторить отправку</button> : <StatusBadge tone="danger"><UserRound size={13} />Нужен исходный контролёр</StatusBadge>}</div></section>}

    {(foreignWorkerPending.pending || foreignWorkerPending.corruption) && <section className="pending-lock" aria-live="assertive"><span className="pending-lock__icon"><CircleStop /></span><div><StatusBadge tone="warning">Другое действие не завершено</StatusBadge><h2>Операция ожидает подтверждения</h2><p>Завершите её под исходной учётной записью. Проверка ОТК пока заблокирована.</p></div><div className="pending-lock__actions"><StatusBadge tone="danger">Нужен исходный работник</StatusBadge></div></section>}

    {activity.error ? <ErrorState title="Не удалось обновить итоги ОТК" message={activity.error.message} onRetry={() => void activity.reload()} /> : !activity.data?.context ? <section className="workspace-section worker-session-setup"><SectionHeader title="Выберите рабочее место ОТК" /><form className="session-form" onSubmit={openSession}><label className="field"><span>Ряд</span><select value={setupRow} onChange={(event) => setSetupRow(event.target.value)}>{qcRows.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label><label className="field"><span>Рабочее место</span><select value={setupStation} onChange={(event) => setSetupStation(event.target.value)}>{qcStations.map((station) => <option key={station.id} value={station.id}>{station.name}</option>)}</select></label><label className="field"><span>Операция</span><select value={setupStep} onChange={(event) => setSetupStep(event.target.value)}>{qcSteps.map((step) => <option key={step.id} value={step.id}>{step.name}</option>)}</select></label><button className="button button--primary" disabled={blocked || !setupStation || !setupStep} type="submit">Начать работу</button></form></section> : <>
      <section className="worker-scan-workspace qc-inspection-workspace">
        <div className="worker-operation-context"><div><span>Ряд</span><strong>{activity.data.context.row?.name ?? "ОТК"}</strong></div><div><span>Операция</span><strong>{activity.data.context.route_step?.name ?? "Контроль"}</strong></div></div>
        <div className="worker-scan-main">
          <form className="worker-scan-form qc-inspection-form" onSubmit={(event) => { event.preventDefault(); if (decision) void submitDecision(decision); }}>
            <label htmlFor="qc-qr-input">QR узла или изделия</label>
            <span className="sr-only" id="qc-scan-hint">После сканирования выберите Годен или Брак.</span>
            <div className="scan-input-wrap worker-scan-input"><ScanLine aria-hidden="true" /><input ref={inputRef} id="qc-qr-input" aria-describedby="qc-scan-hint" value={qr} disabled={blocked} onChange={(event) => { setQr(event.target.value); setDecision(null); setDefectCode(""); setResult(null); setError(null); }} placeholder="Отсканируйте QR" autoComplete="off" autoFocus /></div>
            <div className="qc-decision-buttons" aria-label="Результат проверки"><button className="button qc-decision-button qc-decision-button--accept" type="button" disabled={blocked || !qr.trim()} onClick={() => { setDecision("ACCEPT"); setDefectCode(""); void submitDecision("ACCEPT"); }}><Check />Годен</button><button className="button qc-decision-button qc-decision-button--reject" type="button" aria-pressed={decision === "REJECT"} disabled={blocked || !qr.trim()} onClick={() => { setDecision("REJECT"); setError(null); }}><X />Брак</button></div>
            {decision === "REJECT" && <div className="qc-reject-reason"><label className="field"><span>Причина брака</span><select value={defectCode} onChange={(event) => setDefectCode(event.target.value)} required autoFocus disabled={reasons.loading || Boolean(reasons.error)}><option value="">{reasons.loading ? "Загружаем причины…" : "Выберите причину"}</option>{reasons.data?.items.map((reason) => <option key={reason.code} value={reason.code}>{reason.label}</option>)}</select></label><button className="button button--danger" type="submit" disabled={blocked || reasons.loading || Boolean(reasons.error) || !defectCode}>{busy ? <LoaderCircle className="spin" /> : <Keyboard />}Подтвердить брак</button>{reasons.error && <div className="qc-reason-error" role="alert"><span>Причины не загрузились.</span><button className="text-button" type="button" onClick={() => void reasons.reload()}>Повторить</button></div>}</div>}
          </form>
          <aside className="worker-count" aria-live="polite"><span>Проверено за смену</span><strong data-testid="qc-checked-count">{activity.loading ? "…" : checked ?? "—"}</strong><p>решений ОТК</p><small>Повторный контроль: <b data-testid="qc-reinspection-count">{activity.loading ? "…" : repeated ?? "—"}</b></small></aside>
        </div>

        {result?.terminal && (() => { const presentation = result.inspection ? decisionPresentation(result.inspection) : null; return <div className="worker-current-result qc-current-result" data-status={result.status} role="status">{result.duplicate ? <RotateCcw /> : presentation?.label === "Исправлено" ? <AlertTriangle /> : result.inspection?.decision === "ACCEPT" ? <CheckCircle2 /> : <AlertTriangle />}<div><StatusBadge tone={presentation?.tone ?? "danger"}>{result.duplicate ? "Уже учтено" : presentation?.label ?? "Не принято"}</StatusBadge><strong>{result.message ?? (result.inspection ? "Результат проверки сохранён" : "Исправьте данные и повторите")}</strong></div></div>; })()}

        {selectedRework && <details className="qc-rework-details"><summary><Wrench size={16} />Открыть переделку</summary><p>Это отдельное действие после решения ОТК.</p><div className="qc-rework-form"><label className="field"><span>Проверка с браком</span><select value={selectedRework.decision_id} onChange={(event) => setReworkDecisionId(event.target.value)}>{reworkCandidates.map((item) => <option key={item.decision_id} value={item.decision_id}>{item.subject_qr} · {item.defect_label ?? item.defect_code ?? "Причина не указана"}</option>)}</select></label><label className="field"><span>Повторная операция</span><select value={reworkStep} onChange={(event) => setReworkStep(event.target.value)}><option value="">Выберите</option>{reworkSteps.map((step) => <option key={step.id} value={step.id}>{step.name}</option>)}</select></label><label className="field"><span>Причина переделки</span><input value={reworkReason} onChange={(event) => setReworkReason(event.target.value)} /></label><button className="button button--secondary" type="button" disabled={busy || !reworkStep || !reworkReason.trim()} onClick={() => void openRework()}>Открыть</button></div>{reworkMessage && <p className="form-success" role="status">{reworkMessage}</p>}</details>}
      </section>

      <section className="workspace-section worker-history qc-history" aria-labelledby="qc-history-title"><div className="section-header"><div><h2 id="qc-history-title">Последние проверки</h2><p>Сохранённые решения за смену · время сервера</p></div><button className="icon-button" type="button" aria-label="Обновить последние проверки" disabled={activity.loading} onClick={() => void activity.reload()}><RefreshCw /></button></div>{activity.data.recent_inspections.length === 0 ? <div className="worker-history-empty"><Clock3 /><div><strong>Проверок пока нет</strong><p>После подтверждения результат появится здесь.</p></div></div> : <ol className="worker-history-list qc-history-list">{activity.data.recent_inspections.map((item) => { const presentation = decisionPresentation(item); return <li key={item.inspection_id}><time dateTime={item.created_at}>{formatDateTime(item.created_at)}</time><code>{item.subject_qr}</code><span>{item.decision === "REJECT" ? item.defect_label ?? item.defect_code ?? "Причина не указана" : "—"}</span><StatusBadge compact tone={presentation.tone}>{presentation.label}</StatusBadge></li>; })}</ol>}</section>
    </>}
  </div>;
}
