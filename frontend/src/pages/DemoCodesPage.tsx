import { ArrowLeft, Check, Copy, Printer, QrCode as QrIcon } from "lucide-react";
import { useState } from "react";
import QRCode from "react-qr-code";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Bootstrap } from "../api/types";
import { useAuth } from "../app/AuthContext";
import { canAccess } from "../app/capabilities";
import { useResource } from "../app/useResource";
import { AccessDenied } from "../components/AccessDenied";
import { EmptyState, ErrorState, LoadingState } from "../components/PageState";
import { PageHeader } from "../components/PageHeader";

export function DemoCodesPage() {
  const { user } = useAuth();
  const bootstrap = useResource(() => api.get<Bootstrap>("/bootstrap"), []);
  const [copied, setCopied] = useState<string | null>(null);
  if (!user || !canAccess(user, "scan")) return <AccessDenied />;

  async function copy(value: string) {
    await navigator.clipboard.writeText(value);
    setCopied(value);
    window.setTimeout(() => setCopied((current) => current === value ? null : current), 1500);
  }

  return <div className="page demo-codes-page">
    <PageHeader title="Демо QR-коды" description="Сканируемые коды генерируются из seed-значений backend. Их можно распечатать для проверки USB/HID-сканера." meta={<span className="demo-marker">ДЕМО</span>} actions={<div className="print-actions"><Link className="button button--secondary" to="/scan"><ArrowLeft />К сканированию</Link><button className="button button--primary" type="button" onClick={() => window.print()}><Printer />Печать</button></div>} />
    <div className="print-note"><QrIcon /><p>Печатайте в масштабе 100%. Это синтетические идентификаторы, они не относятся к реальным изделиям.</p></div>
    {bootstrap.loading ? <LoadingState rows={6} /> : bootstrap.error ? <ErrorState message={bootstrap.error.message} onRetry={() => void bootstrap.reload()} /> : bootstrap.data?.sample_qr.length ? <section className="qr-sheet" aria-label="Лист демо QR-кодов">{bootstrap.data.sample_qr.map((sample) => <article className="qr-label" key={sample}>
      <div className="qr-canvas"><QRCode value={sample} size={156} bgColor="transparent" fgColor="currentColor" level="M" /></div>
      <div className="qr-label__copy"><span>Синтетический идентификатор</span><h2>{sample.includes("FINAL") ? "Готовое изделие" : sample.includes("COMP") ? "Деталь" : "WIP / узел"}</h2><code>{sample}</code></div>
      <button className="icon-button qr-copy" type="button" onClick={() => void copy(sample)} aria-label={`Скопировать ${sample}`}>{copied === sample ? <Check /> : <Copy />}</button>
    </article>)}</section> : <EmptyState title="Демо-коды не получены" message="Bootstrap не вернул seed codes. Frontend не создаёт собственные производственные идентификаторы." />}
  </div>;
}

