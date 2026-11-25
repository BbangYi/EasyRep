import { LiveWorkspace } from "./live-workspace";
import { AppInstallProvider } from "./app-install";
import { useLiveQuery } from "./use-live-query";
import type { AuthSession } from "../lib/habitat/session";

export function AuthenticatedApp() {
  return <AppInstallProvider><SessionGate /></AppInstallProvider>;
}

function SessionGate() {
  const query = useLiveQuery<AuthSession>("/api/session/", 15000);
  const session = query.data;
  const valid = session?.user && Array.isArray(session.enclosures) && session.csrfToken;
  const error = query.error || (session && !valid ? "접속 정보를 확인할 수 없습니다." : "");
  if (!valid) return (
    <main className="session-message" aria-live="polite">
      <h1>{error ? "연결 확인 필요" : "접속 확인 중"}</h1>
      <p>{error || "잠시만 기다려 주세요."}</p>
      {error && <button className="button" onClick={query.refresh} disabled={query.refreshing || query.offline}>
        {query.refreshing ? "확인 중…" : "다시 확인"}
      </button>}
    </main>
  );
  return <LiveWorkspace session={session!} connectionError={query.error} />;
}
