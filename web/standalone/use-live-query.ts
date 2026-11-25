import { useEffect, useRef, useState } from "react";

const refreshEvent = "habitatos:refresh";
export function refreshLiveQueries() {
  window.dispatchEvent(new Event(refreshEvent));
}

export function loginReturnUrl(hash: string) {
  // The return destination is always the dashboard on this origin.
  return `/login/?next=${encodeURIComponent(`/${hash.startsWith("#") ? hash : ""}`)}`;
}

class QueryError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

export type LiveQueryResult<T> = {
  url: string | null;
  data?: T;
  error?: string;
  updatedAt?: string;
  refreshing: boolean;
  offline: boolean;
};

export function useLiveQuery<T>(url: string | null, refreshMs = 10000) {
  const [result, setResult] = useState<LiveQueryResult<T>>({
    url: null, refreshing: false, offline: !navigator.onLine,
  });
  const reload = useRef<() => void>(() => {});
  useEffect(() => {
    if (!url) return;
    let disposed = false;
    let running = false;
    let controller: AbortController | undefined;
    const fail = (message: string, keepPrevious = true) => {
      if (!disposed) setResult((previous) => ({
        ...(keepPrevious && previous.url === url ? previous : {}),
        url, error: message, refreshing: false, offline: !navigator.onLine,
      }));
    };
    async function load() {
      if (disposed || running || document.hidden) return;
      if (!navigator.onLine) {
        fail("인터넷 연결이 끊겼습니다. 연결되면 자동으로 다시 조회합니다.");
        return;
      }
      running = true;
      controller = new AbortController();
      const timer = window.setTimeout(() => controller?.abort(), 8000);
      setResult((previous) => ({
        ...(previous.url === url ? previous : {}),
        url, refreshing: true, offline: false,
      }));
      try {
        const response = await fetch(url!, {
          credentials: "same-origin", cache: "no-store", signal: controller.signal,
        });
        if (disposed) return;
        if (response.status === 401) {
          fail("로그인이 필요합니다.", false);
          window.location.replace(loginReturnUrl(window.location.hash));
          return;
        }
        if (!response.ok) throw new QueryError(
          response.status === 403 || response.status === 404
            ? "조회 권한이 없거나 등록 정보가 변경되었습니다."
            : response.status === 503
              ? "사이트 점검 중입니다. 잠시 후 다시 조회해 주세요."
              : "서버에서 데이터를 불러오지 못했습니다. 자동으로 다시 조회합니다.",
          response.status,
        );
        const data: T = await response.json();
        if (!disposed) setResult({
          url, data, updatedAt: new Date().toISOString(), refreshing: false, offline: false,
        });
      } catch (cause) {
        // Permission changes and maintenance must remove previously visible data.
        const keepPrevious = !(cause instanceof QueryError) ||
          (cause.status >= 500 && cause.status !== 503);
        fail(cause instanceof QueryError ? cause.message :
          !navigator.onLine ? "인터넷 연결이 끊겼습니다. 연결되면 자동으로 다시 조회합니다." :
          cause instanceof Error && cause.name === "AbortError"
            ? "서버 응답이 늦습니다. 자동으로 다시 조회합니다."
            : "서버에 연결하지 못했습니다. 자동으로 다시 조회합니다.", keepPrevious);
      } finally {
        window.clearTimeout(timer);
        running = false;
      }
    }
    const refresh = () => { void load(); };
    const offline = () => {
      controller?.abort();
      fail("인터넷 연결이 끊겼습니다. 연결되면 자동으로 다시 조회합니다.");
    };
    reload.current = refresh;
    void load();
    const interval = window.setInterval(refresh, refreshMs);
    document.addEventListener("visibilitychange", refresh);
    window.addEventListener("focus", refresh);
    window.addEventListener("pageshow", refresh);
    window.addEventListener("online", refresh);
    window.addEventListener("offline", offline);
    window.addEventListener(refreshEvent, refresh);
    return () => {
      disposed = true;
      reload.current = () => {};
      controller?.abort();
      window.clearInterval(interval);
      document.removeEventListener("visibilitychange", refresh);
      window.removeEventListener("focus", refresh);
      window.removeEventListener("pageshow", refresh);
      window.removeEventListener("online", refresh);
      window.removeEventListener("offline", offline);
      window.removeEventListener(refreshEvent, refresh);
    };
  }, [url, refreshMs]);
  return {
    ...(result.url === url ? result : { url, refreshing: !!url, offline: !navigator.onLine }),
    refresh: () => reload.current(),
  };
}
