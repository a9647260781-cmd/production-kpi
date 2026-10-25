import { Factory, KeyRound, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Navigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { useAuth } from "../app/AuthContext";
import { defaultLanding } from "../app/capabilities";

const primaryAccounts = [
  { username: "assembly1", label: "Сборка 1" },
  { username: "assembly2", label: "Сборка 2" },
  { username: "assembly3", label: "Сборка 3" },
  { username: "solder", label: "Пайка" },
  { username: "qc", label: "Контролёр ОТК" },
  { username: "foreman", label: "Бригадир" },
  { username: "auditor", label: "Независимый аудитор" },
  { username: "supervisor", label: "Начальник смены" },
];

const extraAccounts = [
  { username: "planner", label: "Планировщик" },
  { username: "admin", label: "Администратор" },
];

export function LoginPage() {
  const { user, login } = useAuth();
  const [username, setUsername] = useState("assembly1");
  const [password, setPassword] = useState("Demo2026!");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  if (user) return <Navigate to={defaultLanding(user)} replace />;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await login(username.trim(), password);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Не удалось войти в демо-контур");
    } finally {
      setSubmitting(false);
    }
  }

  const accounts = expanded ? [...primaryAccounts, ...extraAccounts] : primaryAccounts;

  return (
    <main className="login-page">
      <section className="login-intro" aria-labelledby="login-title">
        <div className="login-intro__brand"><Factory aria-hidden="true" /><span>КПД производства квадрокоптеров</span></div>
        <div>
          <span className="demo-marker demo-marker--large">ДЕМО · синтетические данные</span>
          <h1 id="login-title">Рабочий контур смены — без выдуманных результатов</h1>
          <p>Пять рядов, QR-маршрут, учтённые часы, ОТК и объяснимый расчёт. Выберите роль, чтобы пройти её реальный сценарий через API.</p>
        </div>
        <ul className="login-proof">
          <li><ShieldCheck aria-hidden="true" /><span>Права и scope проверяет backend</span></li>
          <li><KeyRound aria-hidden="true" /><span>Общий пароль действует только в демо-контуре</span></li>
        </ul>
      </section>
      <section className="login-panel" aria-label="Вход в демо-контур">
        <div className="login-panel__heading"><h2>Войти по роли</h2><p>Пароль уже заполнен для локального демо.</p></div>
        <div className="account-picker" role="list" aria-label="Демо-роли">
          {accounts.map((account) => (
            <button key={account.username} type="button" data-selected={username === account.username || undefined} onClick={() => setUsername(account.username)}>
              <span>{account.label}</span><small>{account.username}</small>
            </button>
          ))}
        </div>
        <button className="text-button" type="button" onClick={() => setExpanded((value) => !value)}>{expanded ? "Скрыть служебные роли" : "Показать планировщика и администратора"}</button>
        <form onSubmit={submit} noValidate>
          <label className="field"><span>Логин</span><input name="username" autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} required /></label>
          <label className="field"><span>Пароль</span><input name="password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
          {error && <div className="form-error" role="alert">{error}</div>}
          <button className="button button--primary button--wide" disabled={submitting || !username || !password} type="submit">{submitting ? "Входим…" : "Открыть рабочее место"}</button>
        </form>
        <p className="login-note">План MVP · нормы задаются заводом. Данные этого контура не относятся к реальному производству.</p>
      </section>
    </main>
  );
}

