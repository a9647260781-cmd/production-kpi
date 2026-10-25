import type { QcInspectionBody } from "./types";

export const QC_PENDING_KEY = "kpd-demo.pending-qc-inspection.v1";

export interface PendingQcInspection {
  inspectionId: string;
  actorId: string;
  actorName: string;
  body: Readonly<QcInspectionBody>;
  createdAt: string;
  lastError?: string;
}

export interface QcPendingInspection {
  pending: PendingQcInspection | null;
  corruption: { raw: string; message: string } | null;
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function assertPendingShape(value: unknown): asserts value is PendingQcInspection {
  if (!value || typeof value !== "object") throw new Error("Локальная запись не является объектом.");
  const candidate = value as Partial<PendingQcInspection>;
  const body = candidate.body as Partial<QcInspectionBody> | undefined;
  if (!isNonEmptyString(candidate.inspectionId) || !isNonEmptyString(candidate.actorId) || !isNonEmptyString(candidate.actorName) || !isNonEmptyString(candidate.createdAt)) {
    throw new Error("В локальной записи отсутствуют данные проверки или автора.");
  }
  if (!body || body.inspection_id !== candidate.inspectionId || !isNonEmptyString(body.work_session_id) || !isNonEmptyString(body.subject_qr)) {
    throw new Error("Контекст проверки повреждён или UUID не совпадает.");
  }
  if (body.decision !== "ACCEPT" && body.decision !== "REJECT") throw new Error("Результат проверки имеет недопустимое значение.");
  if (body.decision === "REJECT" && !isNonEmptyString(body.defect_code)) throw new Error("Для брака отсутствует причина.");
  if (body.decision === "ACCEPT" && body.defect_code !== null) throw new Error("Для годного изделия ошибочно сохранена причина брака.");
  if (body.occurred_at_device !== undefined && !isNonEmptyString(body.occurred_at_device)) throw new Error("Время устройства повреждено.");
}

export function inspectQcPending(): QcPendingInspection {
  const raw = localStorage.getItem(QC_PENDING_KEY);
  if (!raw) return { pending: null, corruption: null };
  try {
    const parsed: unknown = JSON.parse(raw);
    assertPendingShape(parsed);
    return { pending: parsed, corruption: null };
  } catch (caught) {
    return {
      pending: null,
      corruption: {
        raw,
        message: caught instanceof Error ? caught.message : "Локальная запись проверки повреждена.",
      },
    };
  }
}

export function readQcPending() {
  return inspectQcPending().pending;
}

export function createQcPending(actorId: string, actorName: string, body: QcInspectionBody) {
  const inspection = inspectQcPending();
  if (inspection.corruption) throw new Error("Повреждённая запись проверки блокирует новое действие. Нужна помощь бригадира.");
  if (inspection.pending) return inspection.pending;
  const pending: PendingQcInspection = {
    inspectionId: body.inspection_id,
    actorId,
    actorName,
    body: Object.freeze({ ...body }),
    createdAt: new Date().toISOString(),
  };
  try {
    localStorage.setItem(QC_PENDING_KEY, JSON.stringify(pending));
  } catch {
    throw new Error("Не удалось надёжно сохранить проверку на устройстве. Отправка не начата.");
  }
  return pending;
}

export function annotateQcPendingError(message: string) {
  const pending = readQcPending();
  if (pending) localStorage.setItem(QC_PENDING_KEY, JSON.stringify({ ...pending, lastError: message }));
}

export function clearQcPending(expectedInspectionId: string) {
  const pending = readQcPending();
  if (pending?.inspectionId === expectedInspectionId) localStorage.removeItem(QC_PENDING_KEY);
}

export function clearCorruptedQcPending(expectedRaw: string) {
  if (localStorage.getItem(QC_PENDING_KEY) === expectedRaw) localStorage.removeItem(QC_PENDING_KEY);
}
