import { AlertTriangle, Inbox, RefreshCw } from "lucide-react";
import type { ReactNode } from "react";

export function LoadingState({ rows = 4, label = "Загрузка данных" }: { rows?: number; label?: string }) {
  return (
    <div className="loading-state" role="status" aria-label={label}>
      {Array.from({ length: rows }, (_, index) => <span className="skeleton-line" key={index} />)}
    </div>
  );
}

export function ErrorState({ title = "Не удалось загрузить данные", message, onRetry }: { title?: string; message: string; onRetry?: () => void }) {
  return (
    <div className="state-panel state-panel--error" role="alert">
      <AlertTriangle aria-hidden="true" />
      <div>
        <h3>{title}</h3>
        <p>{message}</p>
      </div>
      {onRetry && <button className="button button--secondary" type="button" onClick={onRetry}><RefreshCw size={16} />Повторить</button>}
    </div>
  );
}

export function EmptyState({ title, message, action }: { title: string; message: string; action?: ReactNode }) {
  return (
    <div className="state-panel state-panel--empty">
      <Inbox aria-hidden="true" />
      <div>
        <h3>{title}</h3>
        <p>{message}</p>
      </div>
      {action}
    </div>
  );
}

