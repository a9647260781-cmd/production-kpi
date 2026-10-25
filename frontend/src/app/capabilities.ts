import type { User } from "../api/types";

export type UiArea = "dashboard" | "foreman" | "scan" | "entities" | "configuration" | "workforce" | "quality" | "planning" | "reports" | "approve" | "audit";

type RoleName = "WORKER" | "QC" | "FOREMAN" | "AUDITOR" | "PLANNER" | "TECHNOLOGIST" | "SUPERVISOR" | "ADMIN";

const relevantRoles: Record<UiArea, RoleName[]> = {
  dashboard: ["SUPERVISOR", "ADMIN"],
  foreman: ["FOREMAN"],
  scan: ["WORKER", "ADMIN"],
  entities: ["AUDITOR", "TECHNOLOGIST", "SUPERVISOR", "ADMIN"],
  configuration: ["TECHNOLOGIST", "ADMIN"],
  workforce: ["PLANNER", "ADMIN"],
  quality: ["QC", "AUDITOR", "ADMIN"],
  planning: ["PLANNER", "TECHNOLOGIST", "ADMIN"],
  reports: ["AUDITOR", "PLANNER", "TECHNOLOGIST", "SUPERVISOR", "ADMIN"],
  approve: ["SUPERVISOR", "ADMIN"],
  audit: ["AUDITOR", "SUPERVISOR", "ADMIN"],
};

const requiredCapabilities: Record<UiArea, string[]> = {
  dashboard: ["view_reports"],
  foreman: ["view_reports"],
  scan: ["scan"],
  entities: ["read_entities", "manage_genealogy"],
  configuration: ["manage_standards", "manage_genealogy"],
  workforce: ["manage_assignments", "manage_time_entries"],
  quality: ["quality_decide", "quality_audit", "manage_rework"],
  planning: ["manage_plans", "manage_standards"],
  reports: ["view_reports"],
  approve: ["approve_shift"],
  audit: ["view_audit"],
};

function roleNames(user: User) {
  return new Set(user.roles.map((role) => role.name.toUpperCase()));
}

export function canAccess(user: User, area: UiArea) {
  const roles = roleNames(user);
  const capabilities = new Set(user.capabilities);
  if (roles.has("ADMIN") && capabilities.has("admin")) return true;
  return relevantRoles[area].some((role) => roles.has(role))
    && requiredCapabilities[area].some((capability) => capabilities.has(capability));
}

export function defaultLanding(user: User) {
  const roles = roleNames(user);
  if (roles.has("FOREMAN") && canAccess(user, "foreman")) return "/foreman";
  if ((roles.has("ADMIN") && user.capabilities.includes("admin")) || canAccess(user, "dashboard")) return "/";
  if (roles.has("QC") && canAccess(user, "quality")) return "/quality";
  if (roles.has("WORKER") && canAccess(user, "scan")) return "/scan";
  if (roles.has("PLANNER") && canAccess(user, "workforce")) return "/workforce";
  if (roles.has("AUDITOR") && canAccess(user, "quality")) return "/quality";
  if (roles.has("TECHNOLOGIST") && canAccess(user, "configuration")) return "/configuration";
  const fallback = (["scan", "workforce", "quality", "reports", "audit", "entities", "planning", "configuration"] as UiArea[])
    .find((area) => canAccess(user, area));
  return fallback ? `/${fallback}` : "/no-access";
}

export function landingLabel(user: User) {
  const destination = defaultLanding(user);
  if (destination === "/scan") return "К сканированию";
  if (destination === "/workforce") return "К составу и часам";
  if (destination === "/quality") return "К работе ОТК";
  if (destination === "/foreman") return "К своему ряду";
  if (destination === "/configuration") return "К маршрутам и QR";
  if (destination === "/") return "К сводке";
  return "К рабочему экрану";
}

