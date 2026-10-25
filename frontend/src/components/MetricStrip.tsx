import { ChevronRight, CircleHelp } from "lucide-react";
import { formatDecimal, formatRatio } from "../app/format";
import { StatusBadge, type StatusTone } from "./StatusBadge";

interface MetricItem {
  key: string;
  label: string;
  value: string | null;
  hint: string;
  diagnostic?: boolean;
  valueIsPercent?: boolean;
  statusLabel?: string;
  statusTone?: StatusTone;
}

export function MetricStrip({ items, onOpen }: { items: MetricItem[]; onOpen?: () => void }) {
  return (
    <div className="metric-strip" aria-label="Компоненты расчёта">
      {items.map((item) => (
        <button key={item.key} className="metric-cell" type="button" onClick={onOpen} data-diagnostic={item.diagnostic || undefined}>
          <span className="metric-cell__top"><span>{item.label}</span><CircleHelp aria-hidden="true" size={15} /></span>
          <strong>{item.value === null ? "—" : item.valueIsPercent ? `${formatDecimal(item.value, 1)} %` : formatRatio(item.value)}</strong>
          <span className="metric-cell__bottom">
            <StatusBadge compact tone={item.statusTone ?? (item.value === null ? "neutral" : "success")}>{item.statusLabel ?? (item.value === null ? "Нет расчёта" : item.hint)}</StatusBadge>
            <ChevronRight aria-hidden="true" size={16} />
          </span>
        </button>
      ))}
    </div>
  );
}

