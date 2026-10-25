import { FileClock, Filter, RefreshCw } from "lucide-react";
import { useState } from "react";
import { api, query } from "../api/client";
import type { AuditEvent, ListResponse } from "../api/types";
import { useAuth } from "../app/AuthContext";
import { canAccess } from "../app/capabilities";
import { formatDateTime } from "../app/format";
import { useResource } from "../app/useResource";
import { AccessDenied } from "../components/AccessDenied";
import { DataTable, type Column } from "../components/DataTable";
import { EmptyState, ErrorState, LoadingState } from "../components/PageState";
import { PageHeader } from "../components/PageHeader";

export function AuditPage() {
  const { user } = useAuth();
  const [actor, setActor] = useState("");
  const [objectType, setObjectType] = useState("");
  const events = useResource(() => api.get<ListResponse<AuditEvent>>(`/audit${query({ limit: 100 })}`), []);
  if (!user || !canAccess(user, "audit")) return <AccessDenied />;

  const columns: Column<AuditEvent>[] = [
    { key: "time", title: "Время", render: (row) => <time dateTime={row.created_at}>{formatDateTime(row.created_at)}</time> },
    { key: "actor", title: "Кто", render: (row) => <code>{row.actor_user_id.slice(0, 8)}</code> },
    { key: "action", title: "Действие", render: (row) => row.action },
    { key: "object", title: "Объект", render: (row) => <><code>{row.object_id.slice(0, 8)}</code><small className="table-subline">{row.object_type}</small></> },
    { key: "reason", title: "Причина", render: (row) => row.reason ?? "—" },
    { key: "trace", title: "Trace", render: (row) => row.trace_id ? <code>{row.trace_id.slice(0, 10)}</code> : "—" },
  ];

  return <div className="page">
    <PageHeader title="Журнал аудита" description="Неизменяемая история действий, версий и причин. Раздел доступен только для чтения." meta={<span className="demo-marker">ДЕМО</span>} actions={<button className="button button--secondary" type="button" onClick={() => void events.reload()}><RefreshCw />Обновить</button>} />
    <form className="filter-bar" onSubmit={(event) => event.preventDefault()}><Filter aria-hidden="true" /><label className="field"><span>Пользователь</span><input value={actor} onChange={(event) => setActor(event.target.value)} placeholder="Имя или логин" /></label><label className="field"><span>Тип объекта</span><select value={objectType} onChange={(event) => setObjectType(event.target.value)}><option value="">Все</option><option value="operation_event">Событие операции</option><option value="shift">Смена</option><option value="genealogy">Генеалогия</option><option value="quality">ОТК</option><option value="standard">Норма</option><option value="plan">План</option></select></label></form>
    <section className="workspace-section audit-panel">
      {events.loading ? <LoadingState rows={8} /> : events.error ? <ErrorState message={events.error.message} onRetry={() => void events.reload()} /> : events.data?.items.filter((item) => (!actor || item.actor_user_id.includes(actor)) && (!objectType || item.object_type === objectType)).length ? <DataTable columns={columns} rows={events.data.items.filter((item) => (!actor || item.actor_user_id.includes(actor)) && (!objectType || item.object_type === objectType))} getKey={(row) => row.id} caption="События аудита" /> : <EmptyState title="Событий не найдено" message="Измените фильтры или выполните действие в другом разделе." action={<FileClock />} />}
    </section>
  </div>;
}

