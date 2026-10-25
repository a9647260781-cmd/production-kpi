import { LockKeyhole } from "lucide-react";
import { Link } from "react-router-dom";
import { useAuth } from "../app/AuthContext";
import { defaultLanding, landingLabel } from "../app/capabilities";

export function AccessDenied() {
  const { user } = useAuth();
  const landing = user ? defaultLanding(user) : "/login";
  return <div className="standalone-state"><LockKeyhole aria-hidden="true" /><h1>Раздел не входит в задачи этой роли</h1><p>Откройте доступный рабочий раздел. Данные закрытой страницы не загружались.</p><Link className="button button--primary" to={landing}>{user ? landingLabel(user) : "К входу"}</Link></div>;
}

