import { ArrowDown, Box, Link2, QrCode, Search, Unlink, Wrench } from "lucide-react";
import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { EntityTimeline, TrackedEntity } from "../api/types";
import { useAuth } from "../app/AuthContext";
import { canAccess } from "../app/capabilities";
import { formatDateTime, humanize } from "../app/format";
import { AccessDenied } from "../components/AccessDenied";
import { EmptyState, ErrorState, LoadingState } from "../components/PageState";
import { PageHeader, SectionHeader } from "../components/PageHeader";
import { StatusBadge, toneForStatus } from "../components/StatusBadge";

type GenealogyAction = "ATTACH" | "DETACH" | "REPLACE" | "FINALIZE" | "SCRAP";

export function EntitiesPage() {
  const { user } = useAuth();
  const params = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const [qr, setQr] = useState(searchParams.get("qr") ?? "");
  const [entity, setEntity] = useState<TrackedEntity | null>(null);
  const [timeline, setTimeline] = useState<EntityTimeline | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [action, setAction] = useState<GenealogyAction>("ATTACH");
  const [relatedQr, setRelatedQr] = useState("");
  const [replacementQr, setReplacementQr] = useState("");
  const [reason, setReason] = useState("");
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  const canManage = Boolean(user && (user.capabilities.includes("manage_genealogy") || user.capabilities.includes("admin")));

  async function loadByQr(value: string) {
    const clean = value.trim();
    if (!clean) return;
    setLoading(true); setError(null); setActionMessage(null);
    try {
      const found = await api.get<TrackedEntity>(`/entities/by-qr/${encodeURIComponent(clean)}`);
      const details = await api.get<EntityTimeline>(`/entities/${found.id}/timeline`);
      setEntity(found); setTimeline(details); setSearchParams({ qr: clean });
    } catch (caught) {
      setEntity(null); setTimeline(null); setError(caught instanceof Error ? caught.message : "Объект не найден");
    } finally { setLoading(false); }
  }

  useEffect(() => {
    if (params.entityId) {
      setLoading(true);
      api.get<EntityTimeline>(`/entities/${params.entityId}/timeline`).then((details) => { setTimeline(details); setEntity(details.entity); setQr(details.entity.qr_code); }).catch((caught) => setError(caught instanceof Error ? caught.message : "Не удалось загрузить объект")).finally(() => setLoading(false));
    } else if (searchParams.get("qr")) void loadByQr(searchParams.get("qr")!);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.entityId]);

  if (!user || !canAccess(user, "entities")) return <AccessDenied />;

  async function submitAction(event: React.FormEvent) {
    event.preventDefault();
    if (!entity) return;
    setLoading(true); setError(null); setActionMessage(null);
    try {
      const currentQr = entity.qr_code;
      await api.post("/genealogy/actions", {
        request_id: crypto.randomUUID(), action,
        parent_qr: action === "FINALIZE" ? relatedQr.trim() : currentQr,
        child_qr: action === "FINALIZE" ? currentQr : action === "SCRAP" ? currentQr : relatedQr.trim(),
        replacement_qr: action === "REPLACE" ? replacementQr.trim() : null,
        reason: reason.trim() || null,
      });
      setActionMessage("Действие сохранено в генеалогии и журнале аудита.");
      setRelatedQr(""); setReplacementQr(""); setReason("");
      const details = await api.get<EntityTimeline>(`/entities/${entity.id}/timeline`);
      setTimeline(details); setEntity(details.entity);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Не удалось изменить генеалогию"); }
    finally { setLoading(false); }
  }

  return (
    <div className="page">
      <PageHeader title="Изделия и маршрут" description="Прослеживаемость сериализованных деталей: attach / detach / replace, WIP → final, scrap и rework." meta={<span className="demo-marker">ДЕМО</span>} />
      <form className="entity-search" onSubmit={(event) => { event.preventDefault(); void loadByQr(qr); }} role="search">
        <label htmlFor="entity-qr">QR или серийный код</label><div><QrCode aria-hidden="true" /><input id="entity-qr" value={qr} onChange={(event) => setQr(event.target.value)} placeholder="Например, DEMO-WIP-001" /><button className="button button--primary" disabled={loading || !qr.trim()} type="submit"><Search size={16} />Найти</button></div>
      </form>
      {error && <ErrorState message={error} onRetry={entity ? () => void loadByQr(entity.qr_code) : undefined} />}
      {actionMessage && <div className="inline-alert inline-alert--success" role="status"><Link2 /><p>{actionMessage}</p></div>}
      {loading && <LoadingState rows={6} />}
      {!loading && !entity && !error && <EmptyState title="Найдите объект по QR" message="Откроется единая временная шкала операций, связей, ОТК и переделок." />}
      {!loading && entity && timeline && <>
        <section className="entity-summary workspace-section">
          <div className="entity-summary__icon"><Box /></div><div><span>{humanize(entity.entity_type)}</span><h2>{entity.qr_code}</h2><code>{entity.qr_code}</code></div>
          <dl><div><dt>Статус</dt><dd><StatusBadge tone={toneForStatus(entity.status)}>{humanize(entity.status)}</StatusBadge></dd></div><div><dt>Финальный серийный №</dt><dd>{entity.final_serial ?? "Ещё не присвоен"}</dd></div></dl>
        </section>
        <section className="genealogy-flow workspace-section">
          <SectionHeader title="Генеалогия" description="Партийные split/merge не входят в MVP." />
          <div className="genealogy-chain"><div><span>Сериализованные связи</span><strong>{timeline.items.filter((item) => item.kind === "genealogy").length}<small>действий в истории</small></strong></div><ArrowDown aria-hidden="true" /><div className="genealogy-current"><span>Текущий объект</span><strong>{entity.qr_code}<small>{humanize(entity.entity_type)}</small></strong></div><ArrowDown aria-hidden="true" /><div><span>Финальный код</span><strong>{entity.final_serial ?? "Не присвоен"}</strong></div></div>
        </section>
        <section className="entity-grid">
          <div className="workspace-section timeline-panel">
            <SectionHeader title="Маршрут и события" description="Единая серверная шкала без переписывания истории." />
            {timeline.items.length === 0 ? <EmptyState title="Событий ещё нет" message="После первого подтверждённого скана маршрут появится здесь." /> : <ol className="timeline-list">{timeline.items.map((item) => <li key={`${item.kind}-${item.id}-${item.at}`}><span className="timeline-dot" data-kind={item.kind}>{item.kind === "genealogy" ? <Link2 /> : <QrCode />}</span><div><div className="timeline-title"><strong>{item.kind === "route" ? "Операция маршрута" : item.kind === "quality" ? "Решение ОТК" : "Изменение генеалогии"}</strong>{item.status && <StatusBadge compact tone={toneForStatus(item.status)}>{humanize(item.status)}</StatusBadge>}</div><p>{humanize(item.code ?? item.action ?? item.decision ?? item.kind)}{item.defect_code ? ` · дефект ${item.defect_code}` : ""}</p><small>{formatDateTime(item.at)}</small></div></li>)}</ol>}
          </div>
          {canManage && <form className="workspace-section genealogy-form" onSubmit={submitAction}>
            <SectionHeader title="Изменить связь" description="Каждое действие сохраняет причину и историю." />
            <label className="field"><span>Действие</span><select value={action} onChange={(event) => setAction(event.target.value as GenealogyAction)}><option value="ATTACH">Привязать деталь</option><option value="DETACH">Отвязать деталь</option><option value="REPLACE">Заменить деталь</option><option value="FINALIZE">Связать с final QR</option><option value="SCRAP">Списать текущий объект</option></select></label>
            {action !== "SCRAP" && <label className="field"><span>{action === "FINALIZE" ? "Финальный QR" : action === "REPLACE" ? "QR заменяемой детали" : "QR детали"}</span><input value={relatedQr} onChange={(event) => setRelatedQr(event.target.value)} required /></label>}
            {action === "REPLACE" && <label className="field"><span>QR новой детали</span><input value={replacementQr} onChange={(event) => setReplacementQr(event.target.value)} required /></label>}
            <label className="field"><span>Причина</span><textarea value={reason} onChange={(event) => setReason(event.target.value)} rows={3} required /></label>
            <button className="button button--primary" disabled={loading || !reason.trim()} type="submit">{action === "DETACH" ? <Unlink /> : <Link2 />}Сохранить действие</button>
          </form>}
        </section>
      </>}
    </div>
  );
}

