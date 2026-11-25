import { orderOperationalCages, type Cage } from "./live-data";

export type View = "home" | "environment" | "control" | "history" | "management" | "presentation";
export type RecordSection = "overview" | "care" | "device";
export type EnvironmentMode = "measured" | "spatial" | "forecast";
export type WorkspaceRoute = { view: View; id: string; section: RecordSection; mode: EnvironmentMode };

export function readRoute(hash: string): WorkspaceRoute {
  const [path, query] = hash.replace(/^#/, "").split("?");
  const [view, id = ""] = path.split("/");
  const params = new URLSearchParams(query);
  const mode = params.get("mode");
  return {
    view: ["home", "environment", "control", "history", "management", "presentation"].includes(view) ? view as View : "home",
    id: view === "presentation" ? "" : id,
    section: params.get("section") === "device" ? "device" : params.get("section") === "care" ? "care" : "overview",
    mode: mode === "forecast" || mode === "spatial" ? mode : "measured",
  };
}

export function routeHash(route: WorkspaceRoute) {
  if (route.view === "presentation") return "#presentation";
  const params = new URLSearchParams();
  if (route.view === "history" && route.section !== "overview") params.set("section", route.section);
  if (route.view === "environment" && route.mode !== "measured") params.set("mode", route.mode);
  return `#${route.view}${route.id ? `/${route.id}` : ""}${params.size ? `?${params}` : ""}`;
}

export function selectedCage(items: Cage[], id: string) {
  // An explicit URL must never silently select a different enclosure.
  return id ? items.find((item) => item.id === id) : orderOperationalCages(items)[0];
}
