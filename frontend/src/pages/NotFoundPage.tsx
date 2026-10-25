import { ArrowLeft } from "lucide-react";
import { Link } from "react-router-dom";
import { useAuth } from "../app/AuthContext";
import { defaultLanding, landingLabel } from "../app/capabilities";

export function NotFoundPage() {
  const { user } = useAuth();
  const landing = user ? defaultLanding(user) : "/login";
  return <div className="standalone-state"><span>404</span><h1>Такого раздела нет</h1><p>Проверьте адрес или вернитесь к доступному рабочему экрану.</p><Link className="button button--primary" to={landing}><ArrowLeft size={16} />{user ? landingLabel(user) : "К входу"}</Link></div>;
}

