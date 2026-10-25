const dateTimeFormatter = new Intl.DateTimeFormat("ru-RU", {
  day: "2-digit",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

const dateFormatter = new Intl.DateTimeFormat("ru-RU", {
  day: "2-digit",
  month: "long",
  year: "numeric",
});

export function formatDateTime(value?: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : dateTimeFormatter.format(date);
}

export function formatDate(value?: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : dateFormatter.format(date);
}

export function formatDecimal(value?: string | null, maximumFractionDigits = 2) {
  if (value === null || value === undefined || value === "") return "—";
  const parsed = Number(value);
  return Number.isFinite(parsed)
    ? new Intl.NumberFormat("ru-RU", { maximumFractionDigits }).format(parsed)
    : value;
}

export function formatRatio(value?: string | null) {
  if (value === null || value === undefined || value === "") return "—";
  const parsed = Number(value);
  return Number.isFinite(parsed)
    ? new Intl.NumberFormat("ru-RU", { style: "percent", maximumFractionDigits: 1 }).format(parsed)
    : value;
}

const labels: Record<string, string> = {
  INCOMPLETE_DATA: "Неполные данные",
  PROVISIONAL: "Предварительно",
  AWAITING_AUDIT: "Ожидает независимой проверки",
  FINAL: "Оценка завершена",
  QUALITY_GATE_FAILED: "Проверка качества не пройдена",
  draft: "Черновик",
  review: "На проверке",
  approved: "Утверждена",
  reopened: "Переоткрыта",
  closed: "Закрыта",
  active: "Активно",
  attention: "Требует внимания",
  idle: "Нет событий",
  accepted: "Принято",
  rejected: "Отклонено",
  duplicate: "Дубль",
  needs_review: "Нужна проверка",
  ready: "Готово",
  missing: "Нет данных",
  warning: "Предупреждение",
  primary: "Основная работа",
  rework: "Переделка",
  waiting: "Ожидание",
  setup: "Подготовка",
  support: "Поддержка",
  unavailable: "Исключено",
  assembly: "Сборка",
  solder: "Пайка",
  qc: "ОТК",
  supervisor: "Начальник смены",
  worker: "Оператор",
  foreman: "Бригадир",
  auditor: "Независимый аудитор",
  planner: "Планировщик",
  admin: "Администратор",
};

export function humanize(value?: string | null) {
  if (!value) return "Не указано";
  return labels[value] ?? labels[value.toLowerCase()] ?? value.replaceAll("_", " ");
}

