import type { ReactNode } from "react";

export function PageHeader({ title, description, actions, meta }: { title: string; description?: string; actions?: ReactNode; meta?: ReactNode }) {
  return (
    <header className="page-header">
      <div className="page-header__copy">
        <div className="page-header__title-line">
          <h1>{title}</h1>
          {meta}
        </div>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="page-header__actions">{actions}</div>}
    </header>
  );
}

export function SectionHeader({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return (
    <div className="section-header">
      <div><h2>{title}</h2>{description && <p>{description}</p>}</div>
      {action}
    </div>
  );
}

