import { LogOut, ShieldAlert } from "lucide-react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AppShell } from "./app/AppShell";
import { useAuth } from "./app/AuthContext";
import { canAccess, defaultLanding, type UiArea } from "./app/capabilities";
import { AccessDenied } from "./components/AccessDenied";
import { LoadingState } from "./components/PageState";
import { AuditPage } from "./pages/AuditPage";
import { ConfigurationPage } from "./pages/ConfigurationPage";
import { DashboardPage } from "./pages/DashboardPage";
import { DemoCodesPage } from "./pages/DemoCodesPage";
import { EntitiesPage } from "./pages/EntitiesPage";
import { ForemanWorkspacePage } from "./pages/ForemanWorkspacePage";
import { LoginPage } from "./pages/LoginPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { PlanningPage } from "./pages/PlanningPage";
import { QualityPage } from "./pages/QualityPage";
import { QcWorkspacePage } from "./pages/QcWorkspacePage";
import { ReportsPage } from "./pages/ReportsPage";
import { ScanPage } from "./pages/ScanPage";
import { WorkforcePage } from "./pages/WorkforcePage";

function RouteGate({ area, children }: { area: UiArea; children: React.ReactNode }) {
  const { user } = useAuth();
  if (!user || !canAccess(user, area)) return <AccessDenied />;
  return children;
}

function HomeRoute() {
  const { user } = useAuth();
  if (!user) return null;
  if (!canAccess(user, "dashboard")) return <Navigate to={defaultLanding(user)} replace />;
  return <DashboardPage />;
}

function QualityRoute() {
  const { user } = useAuth();
  if (!user) return null;
  const qcOnly = user.roles.length > 0 && user.roles.every((role) => role.name === "QC");
  return qcOnly ? <QcWorkspacePage /> : <QualityPage />;
}

function NoAccessRoute() {
  const { user, logout } = useAuth();
  if (!user) return <Navigate to="/login" replace />;
  const landing = defaultLanding(user);
  if (landing !== "/no-access") return <Navigate to={landing} replace />;
  return <div className="standalone-state"><ShieldAlert aria-hidden="true" /><h1>Нет доступных рабочих разделов</h1><p>Для этой учётной записи не назначены рабочая роль и полномочия. Обратитесь к администратору доступа.</p><button className="button button--primary" type="button" onClick={() => void logout()}><LogOut size={16} />Выйти</button></div>;
}

function ProtectedApp() {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <div className="app-loading"><LoadingState rows={5} label="Проверяем сессию" /></div>;
  if (!user) return <Navigate to="/login" state={{ from: location }} replace />;
  return <AppShell><Routes>
    <Route path="/" element={<HomeRoute />} />
    <Route path="/no-access" element={<NoAccessRoute />} />
    <Route path="/foreman" element={<RouteGate area="foreman"><ForemanWorkspacePage /></RouteGate>} />
    <Route path="/scan" element={<RouteGate area="scan"><ScanPage /></RouteGate>} />
    <Route path="/scan/demo-codes" element={<RouteGate area="scan"><DemoCodesPage /></RouteGate>} />
    <Route path="/entities" element={<RouteGate area="entities"><EntitiesPage /></RouteGate>} />
    <Route path="/entities/:entityId" element={<RouteGate area="entities"><EntitiesPage /></RouteGate>} />
    <Route path="/configuration" element={<RouteGate area="configuration"><ConfigurationPage /></RouteGate>} />
    <Route path="/workforce" element={<RouteGate area="workforce"><WorkforcePage /></RouteGate>} />
    <Route path="/quality" element={<RouteGate area="quality"><QualityRoute /></RouteGate>} />
    <Route path="/planning" element={<RouteGate area="planning"><PlanningPage /></RouteGate>} />
    <Route path="/reports" element={<RouteGate area="reports"><ReportsPage /></RouteGate>} />
    <Route path="/audit" element={<RouteGate area="audit"><AuditPage /></RouteGate>} />
    <Route path="*" element={<NotFoundPage />} />
  </Routes></AppShell>;
}

export function App() {
  return <Routes><Route path="/login" element={<LoginPage />} /><Route path="/*" element={<ProtectedApp />} /></Routes>;
}

