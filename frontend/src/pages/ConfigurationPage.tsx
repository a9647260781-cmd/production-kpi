import { ArrowDown, ArrowUp, Box, CheckCircle2, GitBranch, Plus, RefreshCw, Send, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { Bootstrap, ConfiguredEntity, ListResponse, RouteVersion } from "../api/types";
import { useAuth } from "../app/AuthContext";
import { canAccess } from "../app/capabilities";
import { humanize } from "../app/format";
import { useResource } from "../app/useResource";
import { AccessDenied } from "../components/AccessDenied";
import { EmptyState, ErrorState, LoadingState } from "../components/PageState";
import { PageHeader, SectionHeader } from "../components/PageHeader";
import { StatusBadge, toneForStatus } from "../components/StatusBadge";

interface EditableStep {
  key: string;
  code: string;
  name: string;
  entityType: "COMPONENT" | "WIP";
  allowedRowIds: string[];
  allowsRework: boolean;
}

const blankStep = (): EditableStep => ({ key: crypto.randomUUID(), code: "", name: "", entityType: "WIP", allowedRowIds: [], allowsRework: true });

export function ConfigurationPage() {
  const { user } = useAuth();
  const bootstrap = useResource(() => api.get<Bootstrap>("/bootstrap"), []);
  const routes = useResource(() => api.get<ListResponse<RouteVersion>>("/route-versions"), []);
  const entities = useResource(() => api.get<ListResponse<ConfiguredEntity>>("/tracked-entities?limit=50"), []);
  const [steps, setSteps] = useState<EditableStep[]>([]);
  const [modelId, setModelId] = useState("");
  const [showBuilder, setShowBuilder] = useState(false);
  const [entityQr, setEntityQr] = useState("");
  const [entityType, setEntityType] = useState<"COMPONENT" | "WIP">("WIP");
  const [routeId, setRouteId] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const canRoute = Boolean(user && (user.capabilities.includes("manage_standards") || user.capabilities.includes("admin")));
  const canEntity = Boolean(user && (user.capabilities.includes("manage_genealogy") || user.capabilities.includes("admin")));
  const approvedRoutes = useMemo(() => routes.data?.items.filter((item) => item.status === "APPROVED") ?? [], [routes.data]);

  useEffect(() => {
    const first = approvedRoutes[0];
    if (!routeId && first) setRouteId(first.id);
    if (!modelId && first?.model) setModelId(first.model.id);
  }, [approvedRoutes, modelId, routeId]);

  if (!user || !canAccess(user, "configuration")) return <AccessDenied />;

  function cloneRoute(route: RouteVersion) {
    setModelId(route.model?.id ?? "");
    setSteps(route.steps.map((step) => ({ key: crypto.randomUUID(), code: step.code, name: step.name, entityType: step.entity_type, allowedRowIds: step.allowed_rows.map((row) => row.id), allowsRework: step.allows_rework })));
    setShowBuilder(true); setMessage(null); setError(null);
  }

  function updateStep(index: number, patch: Partial<EditableStep>) {
    setSteps((current) => current.map((step, stepIndex) => stepIndex === index ? { ...step, ...patch } : step));
  }

  function moveStep(index: number, direction: -1 | 1) {
    setSteps((current) => {
      const target = index + direction;
      if (target < 0 || target >= current.length) return current;
      const next = [...current];
      const sourceStep = next[index];
      const targetStep = next[target];
      if (!sourceStep || !targetStep) return current;
      next[index] = targetStep;
      next[target] = sourceStep;
      return next;
    });
  }

  async function createRoute(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true); setError(null); setMessage(null);
    try {
      await api.post("/route-versions", {
        model_id: modelId,
        steps: steps.map((step, index) => ({ code: step.code.trim(), name: step.name.trim(), sequence: index + 1, entity_type: step.entityType, allowed_row_ids: step.allowedRowIds, allows_rework: step.allowsRework })),
      });
      setMessage("Черновик маршрута создан новой версией. Опубликуйте его только после проверки порядка и рядов.");
      setShowBuilder(false); setSteps([]); await routes.reload();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Не удалось создать маршрут"); }
    finally { setBusy(false); }
  }

  async function publish(route: RouteVersion) {
    if (!window.confirm(`Опубликовать маршрут v${route.version}? После публикации он станет неизменяемым.`)) return;
    setBusy(true); setError(null); setMessage(null);
    try { await api.post(`/route-versions/${route.id}/publish`); setMessage(`Маршрут v${route.version} опубликован и доступен для новых WIP.`); await routes.reload(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Не удалось опубликовать маршрут"); }
    finally { setBusy(false); }
  }

  async function createEntity(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError(null); setMessage(null);
    try {
      await api.post("/tracked-entities", { qr_code: entityQr.trim(), entity_type: entityType, route_version_id: routeId });
      setMessage(`QR ${entityQr.trim()} зарегистрирован как ${entityType === "WIP" ? "WIP / узел" : "деталь"}.`);
      setEntityQr(""); await entities.reload();
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Не удалось зарегистрировать QR"); }
    finally { setBusy(false); }
  }

  return <div className="page">
    <PageHeader title="Маршруты и новые QR" description="Линейные версии операций, альтернативные сборочные ряды и регистрация сериализованных объектов." meta={<span className="demo-marker">ДЕМО</span>} actions={<button className="button button--secondary" type="button" onClick={() => void Promise.all([routes.reload(), entities.reload()])}><RefreshCw />Обновить</button>} />
    {message && <div className="inline-alert inline-alert--success" role="status"><CheckCircle2 /><p>{message}</p></div>}
    {error && <div className="inline-alert inline-alert--danger" role="alert"><GitBranch /><p>{error}</p></div>}

    <section className="workspace-section">
      <SectionHeader title="Версии маршрута" description="Опубликованные версии неизменяемы; новая версия создаётся из проверенной основы." action={canRoute && !showBuilder ? <button className="button button--primary" type="button" onClick={() => { const base = approvedRoutes[0]; base ? cloneRoute(base) : (setSteps([blankStep()]), setShowBuilder(true)); }}><Plus />Новая версия</button> : undefined} />
      {routes.loading ? <LoadingState rows={5} /> : routes.error ? <ErrorState message={routes.error.message} onRetry={() => void routes.reload()} /> : routes.data?.items.length ? <div className="route-version-list">{routes.data.items.map((route) => <article key={route.id}>
        <div className="route-version__head"><div><strong>{route.model?.name ?? "Модель не найдена"} · v{route.version}</strong><span>{route.steps.length} операций · {route.immutable ? "неизменяемая версия" : "черновик"}</span></div><StatusBadge tone={toneForStatus(route.status)}>{humanize(route.status)}</StatusBadge></div>
        <ol>{route.steps.map((step) => <li key={step.id}><span>{step.sequence}</span><div><strong>{step.name}</strong><code>{step.code}</code></div><small>{step.allowed_rows.map((row) => row.name).join(" / ") || "Ряд не задан"}</small></li>)}</ol>
        {canRoute && <div className="route-version__actions"><button className="button button--quiet" type="button" onClick={() => cloneRoute(route)}>Взять за основу</button>{route.status === "DRAFT" && <button className="button button--primary" disabled={busy} type="button" onClick={() => void publish(route)}><Send />Опубликовать</button>}</div>}
      </article>)}</div> : <EmptyState title="Маршрутов нет" message="Создайте линейный маршрут минимум из одной операции." />}
    </section>

    {showBuilder && <form className="workspace-section route-builder" onSubmit={createRoute}>
      <SectionHeader title="Черновик новой версии" description="Порядок задаётся сверху вниз. Несколько рядов допустимы только для всех трёх сборочных полос." />
      <div className="route-builder__summary"><span>Модель</span><strong>{approvedRoutes.find((route) => route.model?.id === modelId)?.model?.name ?? modelId}</strong><span>Операций</span><strong>{steps.length}</strong></div>
      <div className="route-builder__steps">{steps.map((step, index) => <fieldset key={step.key}><legend>Операция {index + 1}</legend><div className="step-order"><button type="button" className="icon-button" disabled={index === 0} onClick={() => moveStep(index, -1)} aria-label="Поднять операцию"><ArrowUp /></button><button type="button" className="icon-button" disabled={index === steps.length - 1} onClick={() => moveStep(index, 1)} aria-label="Опустить операцию"><ArrowDown /></button></div><label className="field"><span>Код</span><input value={step.code} onChange={(event) => updateStep(index, { code: event.target.value.toUpperCase() })} pattern="[A-Za-z0-9_-]+" required /></label><label className="field"><span>Название</span><input value={step.name} onChange={(event) => updateStep(index, { name: event.target.value })} required /></label><label className="field"><span>Тип объекта</span><select value={step.entityType} onChange={(event) => updateStep(index, { entityType: event.target.value as EditableStep["entityType"] })}><option value="WIP">WIP / узел</option><option value="COMPONENT">Деталь</option></select></label><div className="field route-row-picker"><span>Разрешённые ряды</span>{bootstrap.data?.rows.map((row) => <label key={row.id}><input type="checkbox" checked={step.allowedRowIds.includes(row.id)} onChange={(event) => updateStep(index, { allowedRowIds: event.target.checked ? [...step.allowedRowIds, row.id] : step.allowedRowIds.filter((id) => id !== row.id) })} />{row.name}</label>)}</div><label className="checkbox-field"><input type="checkbox" checked={step.allowsRework} onChange={(event) => updateStep(index, { allowsRework: event.target.checked })} />Разрешить повторную операцию</label><button type="button" className="icon-button" disabled={steps.length === 1} onClick={() => setSteps((current) => current.filter((_, stepIndex) => stepIndex !== index))} aria-label="Удалить операцию"><Trash2 /></button></fieldset>)}</div>
      <div className="form-actions"><button className="button button--quiet" type="button" onClick={() => setShowBuilder(false)}>Отмена</button><button className="button button--secondary" type="button" onClick={() => setSteps((current) => [...current, blankStep()])}><Plus />Добавить операцию</button><button className="button button--primary" type="submit" disabled={busy || !modelId || !steps.length || steps.some((step) => !step.code || !step.name || !step.allowedRowIds.length)}>Создать черновик</button></div>
    </form>}

    <section className="configuration-grid">
      {canEntity && <form className="workspace-section" onSubmit={createEntity}><SectionHeader title="Зарегистрировать новый QR" description="WIP и деталь создаются только на опубликованной версии маршрута." /><label className="field"><span>QR-код</span><input value={entityQr} onChange={(event) => setEntityQr(event.target.value)} placeholder="DEMO-WIP-NEW-001" required /></label><label className="field"><span>Тип</span><select value={entityType} onChange={(event) => setEntityType(event.target.value as typeof entityType)}><option value="WIP">WIP / узел</option><option value="COMPONENT">Деталь</option></select></label><label className="field"><span>Опубликованный маршрут</span><select value={routeId} onChange={(event) => setRouteId(event.target.value)} required>{approvedRoutes.map((route) => <option key={route.id} value={route.id}>{route.model?.name} · v{route.version}</option>)}</select></label><button className="button button--primary" type="submit" disabled={busy || !entityQr.trim() || !routeId}><Box />Создать объект</button></form>}
      <div className="workspace-section"><SectionHeader title="Последние QR" description={`${entities.data?.total ?? 0} сериализованных объектов в P0`} />{entities.loading ? <LoadingState rows={4} /> : entities.error ? <ErrorState message={entities.error.message} onRetry={() => void entities.reload()} /> : entities.data?.items.length ? <ul className="compact-list">{entities.data.items.slice(-8).reverse().map((entity) => <li key={entity.id}><div><code>{entity.qr_code}</code><strong>{entity.entity_type === "WIP" ? "WIP / узел" : "Деталь"}</strong></div><StatusBadge compact tone={toneForStatus(entity.status)}>{humanize(entity.status)}</StatusBadge></li>)}</ul> : <EmptyState title="Объектов нет" message="Зарегистрируйте первый синтетический QR." />}</div>
    </section>
  </div>;
}
