# Design System

## Intent

Сцена: начальник смены в ярко освещённой производственной зоне быстро сверяет пять рядов, исключения и подтверждённые сервером события. Поэтому интерфейс светлый, контрастный, с плотной информацией и минимальным движением.

## Color strategy

Restrained. Нейтральный холодный фон, белые рабочие поверхности, сдержанный синий как единственный основной акцент по мотивам утверждённой инфографики. Янтарный обозначает ожидание/проверку, красный — ошибку, зелёно-бирюзовый — подтверждение. Цвет никогда не работает без текста или пиктограммы.

All implementation colors use OKLCH tokens:

- `--bg: oklch(0.978 0.006 245)`
- `--surface: oklch(1 0 0)`
- `--surface-subtle: oklch(0.955 0.012 242)`
- `--ink: oklch(0.235 0.046 258)`
- `--muted: oklch(0.455 0.032 254)`
- `--primary: oklch(0.54 0.16 246)`
- `--primary-strong: oklch(0.42 0.14 249)`
- `--info: oklch(0.68 0.13 224)`
- `--success: oklch(0.56 0.125 166)`
- `--warning: oklch(0.72 0.14 72)`
- `--danger: oklch(0.56 0.205 27)`

## Typography

One UI family: `Inter`, with system fallbacks. Fixed product scale: 12, 13, 14, 16, 20, 24, 30 px. Tabular numbers use `font-variant-numeric: tabular-nums`. Headings are compact and balanced; labels remain sentence case in Russian.

## Layout

- Desktop: 248 px persistent sidebar, sticky top context bar, content max-width 1480 px.
- Tablet: compact sidebar and responsive two-column regions.
- Mobile: top header plus horizontal navigation; tables receive controlled horizontal containers or list rendering.
- Cards use 12–14 px radius, never nested as decoration. Tables and divided panels carry dense operational information.

## Components

- Buttons: 40 px default, 44 px on scan/mobile surfaces; visible focus, active scale 0.98, disabled and loading states.
- Inputs: explicit label, helper/error association, 42–46 px height.
- Status chips: icon/shape + text; semantic tinted background with readable dark text.
- KPI: one comparative strip with drill-down, not four isolated hero cards.
- Tables: sticky or clear headers, tabular numerals, empty/error/loading rows.
- Feedback: inline banners and compact toasts; no auto-dismiss for errors.

## Motion

Only state feedback: 120–200 ms transform/opacity/color transitions with strong ease-out. No animation for keyboard scan submission or repeated navigation. `prefers-reduced-motion` removes transforms.

