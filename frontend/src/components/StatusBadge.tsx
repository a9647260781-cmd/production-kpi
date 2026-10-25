import { AlertCircle, CheckCircle2, Clock3, Info, MinusCircle } from "lucide-react";
import type { ReactNode } from "react";

export type StatusTone = "neutral" | "info" | "success" | "warning" | "danger";

const icons = {
  neutral: MinusCircle,
  info: Info,
  success: CheckCircle2,
  warning: Clock3,
  danger: AlertCircle,
};

export function StatusBadge({ children, tone = "neutral", compact = false }: { children: ReactNode; tone?: StatusTone; compact?: boolean }) {
  const Icon = icons[tone];
  return (
    <span className="status-badge" data-tone={tone} data-compact={compact || undefined}>
      <Icon aria-hidden="true" size={compact ? 13 : 15} strokeWidth={2.2} />
      <span>{children}</span>
    </span>
  );
}

export function toneForStatus(status: string): StatusTone {
  const value = status.toLowerCase();
  if (["accepted", "approved", "active", "final", "ready", "completed", "closed", "online"].some((key) => value.includes(key))) return "success";
  if (["rejected", "error", "failed", "conflict", "offline", "cancelled"].some((key) => value.includes(key))) return "danger";
  if (["pending", "review", "provisional", "awaiting", "attention", "warning", "incomplete", "draft"].some((key) => value.includes(key))) return "warning";
  if (["accepted", "info"].some((key) => value.includes(key))) return "info";
  return "neutral";
}

