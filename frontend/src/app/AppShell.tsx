import {
  BarChart3,
  ClipboardCheck,
  Factory,
  FileClock,
  Gauge,
  GitBranch,
  LogOut,
  Menu,
  QrCode,
  ScrollText,
  Settings2,
  ShieldCheck,
  UsersRound,
  X,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { canAccess, defaultLanding, type UiArea } from "./capabilities";
import { useAuth } from "./AuthContext";
import { humanize } from "./format";

interface NavItem {
  to: string;
  label: string;
  icon: typeof Factory;
  area?: UiArea;
}

const navigation: NavItem[] = [
  { to: "/", label: "Сводка", icon: Gauge, area: "dashboard" },
  { to: "/scan", label: "Сканирование", icon: QrCode, area: "scan" },
  { to: "/entities", label: "Изделия и маршрут", icon: ScrollText, area: "entities" },
  { to: "/configuration", label: "Маршруты и новые QR", icon: GitBranch, area: "configuration" },
  { to: "/workforce", label: "Состав и часы", icon: UsersRound, area: "workforce" },
  { to: "/quality", label: "ОТК и переделки", icon: ShieldCheck, area: "quality" },
  { to: "/planning", label: "Нормы и план", icon: Settings2, area: "planning" },
  { to: "/reports", label: "Отчёты", icon: BarChart3, area: "reports" },
  { to: "/audit", label: "Журнал аудита", icon: FileClock, area: "audit" },
];

export function AppShell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();

  useEffect(() => setMobileOpen(false), [location.pathname]);
  if (!user) return null;

  const visible = navigation.filter((item) => !item.area || canAccess(user, item.area));
  const landing = defaultLanding(user);
  const workerOnly = user.roles.length > 0 && user.roles.every((role) => role.name === "WORKER");
  const qcOnly = user.roles.length > 0 && user.roles.every((role) => role.name === "QC");
  const foremanOnly = user.roles.length > 0 && user.roles.every((role) => role.name === "FOREMAN");

  if (workerOnly || qcOnly || foremanOnly) {
    const FocusIcon = qcOnly ? ShieldCheck : foremanOnly ? UsersRound : Factory;
    const workspaceLabel = qcOnly ? "Контроль ОТК" : foremanOnly ? "Мой ряд" : "Сканирование";
    return (
      <div className="app-shell focused-shell">
        <a className="skip-link" href="#main-content">К основному содержимому</a>
        <header className="focused-topbar">
          <NavLink className="focused-brand" to={landing} aria-label={foremanOnly ? "К рабочему месту бригадира" : qcOnly ? "К контролю ОТК" : "К сканированию"}><FocusIcon aria-hidden="true" /><strong>{workspaceLabel}</strong></NavLink>
          <div className="focused-identity"><span className="demo-marker">ДЕМО</span><strong>{user.display_name}</strong><button className="icon-button" type="button" onClick={() => void logout()} aria-label="Выйти"><LogOut /></button></div>
        </header>
        <main id="main-content" className="main-content" tabIndex={-1}>{children}</main>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">К основному содержимому</a>
      <header className="mobile-header">
        <button className="icon-button" type="button" onClick={() => setMobileOpen((value) => !value)} aria-expanded={mobileOpen} aria-controls="primary-navigation" aria-label={mobileOpen ? "Закрыть меню" : "Открыть меню"}>
          {mobileOpen ? <X /> : <Menu />}
        </button>
        <NavLink className="mobile-brand" to={landing} aria-label="На стартовый экран" onClick={() => setMobileOpen(false)}><Factory size={18} /><strong>КПД производства</strong></NavLink>
        <span className="demo-marker">ДЕМО</span>
      </header>

      <aside className="sidebar" data-open={mobileOpen || undefined}>
        <NavLink className="brand-block" to={landing} aria-label="На стартовый экран" onClick={() => setMobileOpen(false)}>
          <span className="brand-mark" aria-hidden="true"><Factory /></span>
          <div><strong>КПД производства</strong><span>Квадрокоптеры</span></div>
        </NavLink>
        <div className="demo-banner"><span>ДЕМО</span><p>Только синтетические данные</p></div>
        <nav id="primary-navigation" className="primary-nav" aria-label="Основная навигация">
          {visible.map((item) => {
            const Icon = item.icon;
            return <NavLink key={item.to} to={item.to} end={item.to === "/"} onClick={() => setMobileOpen(false)}><Icon aria-hidden="true" /><span>{item.label}</span></NavLink>;
          })}
        </nav>
        <div className="sidebar-user">
          <div className="avatar" aria-hidden="true">{user.display_name.slice(0, 2).toUpperCase()}</div>
          <div className="sidebar-user__copy"><strong>{user.display_name}</strong><span>{user.roles.map((role) => humanize(role.name)).join(" · ")}</span></div>
          <button className="icon-button" type="button" onClick={() => void logout()} aria-label="Выйти"><LogOut /></button>
        </div>
      </aside>
      {mobileOpen && <button className="sidebar-backdrop" type="button" aria-label="Закрыть меню" onClick={() => setMobileOpen(false)} />}
      <main id="main-content" className="main-content" tabIndex={-1}>{children}</main>
    </div>
  );
}

