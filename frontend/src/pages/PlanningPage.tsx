import { ClipboardList, Plus, RefreshCw, Ruler } from "lucide-react";
import { useState } from "react";
import { api } from "../api/client";
import type { Bootstrap, ListResponse, ProductionPlan, StandardSet } from "../api/types";
import { useAuth } from "../app/AuthContext";
import { canAccess } from "../app/capabilities";
import { formatDate, formatDecimal, humanize } from "../app/format";
import { useResource } from "../app/useResource";
import { AccessDenied } from "../components/AccessDenied";
import { EmptyState, ErrorState, LoadingState } from "../components/PageState";
import { PageHeader, SectionHeader } from "../components/PageHeader";
import { StatusBadge, toneForStatus } from "../components/StatusBadge";

export function PlanningPage() {
  const { user } = useAuth();
  const bootstrap = useResource(() => api.get<Bootstrap>("/bootstrap"), []);
  const plans = useResource(() => api.get<ListResponse<ProductionPlan>>("/plans"), []);
  const standards = useResource(() => api.get<ListResponse<StandardSet>>("/standards"), []);
  const [form, setForm] = useState<"plan" | "standard" | null>(null);
  const [code, setCode] = useState("");
  const [operationId, setOperationId] = useState("");
  const [rowId, setRowId] = useState("");
  const [quantity, setQuantity] = useState("");
  const [minutes, setMinutes] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!user || !canAccess(user, "planning")) return <AccessDenied />;
  const canPlans = user.capabilities.includes("manage_plans") || user.capabilities.includes("admin");
  const canStandards = user.capabilities.includes("manage_standards") || user.capabilities.includes("admin");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const shift = bootstrap.data?.active_shift;
    const step = bootstrap.data?.route_steps.find((item) => item.id === operationId);
    const modelId = standards.data?.items[0]?.model_id ?? plans.data?.items[0]?.lines[0]?.model_id;
    if (!form || !shift || !step || !modelId) { setError("Нет модели из действующей версии норм или плана."); return; }
    setSaving(true); setError(null); setMessage(null);
    try {
      if (form === "plan") {
        await api.post("/plans", { shift_id: shift.id, status: "DRAFT", mode: "PATCH", reason: "Создано в demo UI", lines: [{ key: code, model_id: modelId, route_step_id: step.id, row_id: rowId || null, planned_qty: Number(quantity), norm_minutes: minutes }] });
        setMessage("Новая версия клонирована из текущей: изменена одна строка, остальные позиции сохранены сервером."); await plans.reload();
      } else {
        await api.post("/standards", { model_id: modelId, status: "DRAFT", mode: "PATCH", effective_from: new Date().toISOString(), reason: "Создано в demo UI", values: [{ route_step_id: step.id, norm_minutes: minutes }] });
        setMessage("Набор норм клонирован: изменена одна операция, остальные нормы сохранены сервером."); await standards.reload();
      }
      setForm(null); setCode(""); setQuantity(""); setMinutes("");
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Не удалось создать версию"); }
    finally { setSaving(false); }
  }

  return <div className="page">
    <PageHeader title="Нормы и план" description="Версии определяют пооперационный A_plan и производительность. Опубликованная версия не редактируется задним числом." meta={<span className="demo-marker">ДЕМО</span>} actions={<button className="button button--secondary" onClick={() => void Promise.all([plans.reload(), standards.reload()])} type="button"><RefreshCw />Обновить</button>} />
    {message && <div className="inline-alert inline-alert--success" role="status"><ClipboardList /><p>{message}</p></div>}
    {error && <div className="inline-alert inline-alert--danger" role="alert"><Ruler /><p>{error}</p></div>}
    {form && <form className="workspace-section version-form" onSubmit={submit}>
      <SectionHeader title={form === "plan" ? "Новая версия плана" : "Новый набор норм"} description="Режим PATCH клонирует текущую версию и меняет только указанную строку; остальные позиции сохраняются." />
      <div className="context-bar"><div><span>Основа</span><strong>{form === "plan" ? `План v${plans.data?.items[0]?.version ?? "—"} · ${plans.data?.items[0]?.lines.length ?? 0} строк` : `Нормы v${standards.data?.items[0]?.version ?? "—"} · ${standards.data?.items[0]?.values.length ?? 0} операций`}</strong></div><div><span>Изменение</span><strong>1 строка</strong></div><div><span>Полная замена</span><strong>Не выполняется</strong></div></div>
      <div className="inline-form">
        <label className="field"><span>Код версии</span><input value={code} onChange={(event) => setCode(event.target.value)} required placeholder={form === "plan" ? "PLAN-DEMO-02" : "STD-DEMO-02"} /></label>
        <label className="field"><span>Операция</span><select value={operationId} onChange={(event) => setOperationId(event.target.value)} required><option value="">Выберите</option>{bootstrap.data?.route_steps.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
        {form === "plan" && <><label className="field"><span>Ряд (необязательно)</span><select value={rowId} onChange={(event) => setRowId(event.target.value)}><option value="">Любой допустимый</option>{bootstrap.data?.rows.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label><label className="field"><span>Количество</span><input inputMode="numeric" value={quantity} onChange={(event) => setQuantity(event.target.value)} required /></label></>}
        <label className="field"><span>Норма, чел.-мин</span><input inputMode="decimal" value={minutes} onChange={(event) => setMinutes(event.target.value.replace(",", "."))} required /></label>
        <div className="form-actions"><button className="button button--quiet" type="button" onClick={() => setForm(null)}>Отмена</button><button className="button button--primary" disabled={saving} type="submit">Создать черновик</button></div>
      </div>
    </form>}
    <section className="planning-grid">
      <div className="workspace-section">
        <SectionHeader title="Планы" description="Сверхплан одной позиции не закрывает дефицит другой." action={canPlans ? <button className="button button--primary" type="button" onClick={() => setForm("plan")}><Plus />Новая версия</button> : undefined} />
        {plans.loading ? <LoadingState rows={5} /> : plans.error ? <ErrorState message={plans.error.message} onRetry={() => void plans.reload()} /> : plans.data?.items.length ? <div className="version-list">{plans.data.items.map((plan) => <article key={plan.id}><div className="version-list__top"><div><strong>План v{plan.version}</strong><span>{plan.approved_at ? `утверждён ${formatDate(plan.approved_at)}` : "черновик"}</span></div><StatusBadge tone={toneForStatus(plan.status)}>{humanize(plan.status)}</StatusBadge></div><div className="version-lines">{plan.lines.map((line) => <div key={line.id}><span>{bootstrap.data?.route_steps.find((step) => step.id === line.route_step_id)?.name ?? line.key}{line.row_id ? ` · ${bootstrap.data?.rows.find((row) => row.id === line.row_id)?.name ?? line.row_id}` : ""}</span><strong>{formatDecimal(String(line.planned_qty))} шт.</strong><small>{formatDecimal(line.norm_minutes)} чел.-мин</small></div>)}</div></article>)}</div> : <EmptyState title="Планов нет" message="Создайте первую учебную версию плана для активной смены." />}
      </div>
      <div className="workspace-section">
        <SectionHeader title="Нормы" description="Нормы задаются заводом; демо-версии всегда явно маркированы." action={canStandards ? <button className="button button--primary" type="button" onClick={() => setForm("standard")}><Plus />Новый набор</button> : undefined} />
        {standards.loading ? <LoadingState rows={5} /> : standards.error ? <ErrorState message={standards.error.message} onRetry={() => void standards.reload()} /> : standards.data?.items.length ? <div className="version-list">{standards.data.items.map((set) => <article key={set.id}><div className="version-list__top"><div><strong>Нормы v{set.version}</strong><span>с {formatDate(set.effective_from)}</span></div><StatusBadge tone={toneForStatus(set.status)}>{humanize(set.status)}</StatusBadge></div><div className="version-lines">{set.values.map((value) => <div key={value.route_step_id}><span>{bootstrap.data?.route_steps.find((step) => step.id === value.route_step_id)?.name ?? value.route_step_id}</span><strong>{formatDecimal(value.norm_minutes)} чел.-мин</strong><small>Модель {set.model_id.slice(0, 8)}</small></div>)}</div></article>)}</div> : <EmptyState title="Нормы не загружены" message="Без действующей нормы KPI на нормо-часах остаются недоступны." />}
      </div>
    </section>
  </div>;
}

