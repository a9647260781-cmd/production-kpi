import type { OperationEventBody, OperationEventResult } from "./types";

export const PENDING_KEY = "kpd-demo.pending-scan.v1";

export interface PendingScan {
  eventId: string;
  actorId: string;
  actorName: string;
  body: Readonly<OperationEventBody>;
  createdAt: string;
  lastError?: string;
}

export interface PendingInspection {
  pending: PendingScan | null;
  corruption: { raw: string; message: string } | null;
}

export function inspectPendingScan(): PendingInspection {
  const raw = localStorage.getItem(PENDING_KEY);
  if (!raw) return { pending: null, corruption: null };
  try {
    const parsed = JSON.parse(raw) as PendingScan;
    if (!parsed.eventId || !parsed.actorId || !parsed.body || parsed.body.event_id !== parsed.eventId) {
      throw new Error("В локальной записи отсутствуют обязательные поля или не совпадает UUID события.");
    }
    return { pending: parsed, corruption: null };
  } catch (caught) {
    return {
      pending: null,
      corruption: {
        raw,
        message: caught instanceof Error ? caught.message : "Локальная запись повреждена.",
      },
    };
  }
}

export function readPendingScan(): PendingScan | null {
  return inspectPendingScan().pending;
}

export function createPendingScan(actorId: string, actorName: string, body: OperationEventBody): PendingScan {
  const inspection = inspectPendingScan();
  if (inspection.corruption) throw new Error("Повреждённая локальная запись блокирует новый скан. Нужна помощь бригадира.");
  const existing = inspection.pending;
  if (existing) return existing;
  const pending: PendingScan = {
    eventId: body.event_id,
    actorId,
    actorName,
    body: Object.freeze({ ...body }),
    createdAt: new Date().toISOString(),
  };
  localStorage.setItem(PENDING_KEY, JSON.stringify(pending));
  return pending;
}

export function annotatePendingError(message: string) {
  const pending = readPendingScan();
  if (!pending) return;
  localStorage.setItem(PENDING_KEY, JSON.stringify({ ...pending, lastError: message }));
}

export function clearPendingScan(expectedEventId: string) {
  const pending = readPendingScan();
  if (pending?.eventId === expectedEventId) localStorage.removeItem(PENDING_KEY);
}

export function clearCorruptedPending(expectedRaw: string) {
  if (localStorage.getItem(PENDING_KEY) === expectedRaw) localStorage.removeItem(PENDING_KEY);
}

export function isServerAcknowledgement(result: OperationEventResult) {
  return result.terminal === true || ["ACCEPTED", "NEEDS_REVIEW", "CANCELLED"].includes(result.status);
}

