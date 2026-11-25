import { EnclosurePhoto } from "./enclosure-photo";
import { EnclosureViewer, GatewayCameraViewer } from "./enclosure-viewer";
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import {
  Activity,
  BookOpen,
  RefreshCw,
  ChevronDown,
  CircleAlert,
  UserRound,
  CircuitBoard,
  ChartNoAxesCombined,
  History,
  LayoutDashboard,
  Layers3,
  Settings2,
  SlidersHorizontal,
} from "lucide-react";
import { BrandLogo } from "../components/habitat/brand-logo";
import {
  ForestEntrance,
  useForestMotion,
} from "../components/habitat/forest-motion";
import { managementLabels, type AuthSession } from "../lib/habitat/session";
import { dateTime, measurementStatus, operationalStatus, orderOperationalCages, type Cage } from "./live-data";
import { refreshLiveQueries, useLiveQuery } from "./use-live-query";
import {
  Panel,
  Empty,
  Notice,
  Badge,
  EnvironmentSummary,
  DeviceRows,
} from "./live-panels";
import { EnvironmentWorkspace } from "./live-environment";
import { readRoute, routeHash, selectedCage, type View, type WorkspaceRoute } from "./live-route";
import { Control } from "./live-control";
import { HistoryOverview } from "./history-overview";
import { CareRecords, RecordWorkspace } from "./care-records";
import { Management } from "./live-management";
import "./live-workspace.css";

const Presentation = lazy(() => import("./presentation"));
const tabs = [
  { id: "home", label: "홈", title: "사육장 현황", icon: LayoutDashboard },
  {
    id: "environment",
    label: "환경",
    title: "환경 상세",
    icon: ChartNoAxesCombined,
  },
  {
    id: "control",
    label: "제어",
    title: "장치 상태·제어",
    icon: SlidersHorizontal,
  },
  { id: "history", label: "기록", title: "운영 기록", icon: History },
  { id: "management", label: "관리", title: "사육장 관리", icon: Settings2 },
] as const;
const route = () => readRoute(window.location.hash);
export function LiveWorkspace({ session, connectionError }: { session: AuthSession; connectionError?: string }) {
  const referrer = new URL(document.referrer || window.location.origin);
  const returningFromForm = referrer.origin === window.location.origin && referrer.pathname.startsWith("/manage/");
  const motion = useForestMotion(!returningFromForm);
  const [location, setLocation] = useState(route);
  const returnRoute = useRef<WorkspaceRoute>({ view: "home", id: "", section: "overview", mode: "measured" });
  const [showAllCages, setShowAllCages] = useState(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const accountMenu = useRef<HTMLDetailsElement>(null);
  const [savedCare, setSavedCare] = useState(false);
  useEffect(() => {
    try {
      const prefix = `habitatos:care-draft:${session.user.id}:`;
      Object.keys(sessionStorage).filter((key) => key.startsWith("habitatos:care-draft:") && !key.startsWith(prefix)).forEach((key) => sessionStorage.removeItem(key));
    } catch { /* Storage may be disabled. */ }
    const url = new URL(window.location.href);
    const saved = url.searchParams.get("care_saved");
    if (!saved) return;
    try { sessionStorage.removeItem(`habitatos:care-draft:${session.user.id}:${saved}`); } catch { /* Storage may be disabled. */ }
    url.searchParams.delete("care_saved");
    window.history.replaceState(window.history.state, "", url.pathname + url.search + url.hash);
    setSavedCare(true);
  }, [session.user.id]);
  const list = useLiveQuery<{
    items: Cage[];
    asOf: string;
    truncated: boolean;
  }>("/api/enclosures/");
  const items = list.data?.items || [];
  const orderedItems = orderOperationalCages(items);
  // The home view is the current operating surface, not a list of every
  // enclosure that has ever produced a sensor reading. Keep delayed records
  // available under "확인 필요" without presenting them as another live Pi.
  const sensorCages = orderedItems.filter((item) => operationalStatus(item).kind === "sensor-current");
  const pendingCages = orderedItems.filter((item) => {
    const kind = operationalStatus(item).kind;
    return kind === "sensor-delayed" || kind === "pi-waiting" || kind === "unregistered";
  });
  const simulatedCages = orderedItems.filter((item) => operationalStatus(item).kind === "simulation");
  const cage = selectedCage(items, location.id);
  const primaryCages = sensorCages.length ? sensorCages : cage ? [cage] : [];
  const homeCages = showAllCages
    ? orderedItems
    : [...primaryCages, ...(cage && !primaryCages.some((item) => item.id === cage.id) ? [cage] : [])];
  const nonSensorCageCount = pendingCages.length + simulatedCages.length;
  const measurement = cage ? measurementStatus(cage) : null;
  const awaitingDevice = Boolean(cage && !cage.sampledAt && cage.gateway.status === "unregistered");
  const tab = tabs.find((t) => t.id === location.view);
  useEffect(() => {
    const read = () => {
      setLocation(route());
      if (accountMenu.current) accountMenu.current.open = false;
    };
    window.addEventListener("popstate", read);
    window.addEventListener("hashchange", read);
    return () => {
      window.removeEventListener("popstate", read);
      window.removeEventListener("hashchange", read);
    };
  }, []);
  function navigate(view: View, id = location.id || cage?.id || "", detail: Partial<Pick<WorkspaceRoute, "section" | "mode">> = {}) {
    if (view === "presentation" && location.view !== "presentation") returnRoute.current = location;
    const next = { view, id: view === "presentation" ? "" : id, section: location.section, mode: location.mode, ...detail };
    window.history.pushState(
      window.history.state,
      "",
      routeHash(next),
    );
    setLocation(next);
    setShowAllCages(false);
    if (accountMenu.current) accountMenu.current.open = false;
    window.scrollTo({ top: 0, behavior: "instant" });
    requestAnimationFrame(() =>
      heading.current?.focus({ preventScroll: true }),
    );
  }
  return (
    <div className="forest-scene live-workspace" data-connection-error={Boolean(connectionError || list.error)}>
      <a href="#live-content" className="live-skip" onClick={(event) => {
        // The hash belongs to the workspace router; skipping must preserve it.
        event.preventDefault();
        heading.current?.focus();
      }}>
        본문으로 이동
      </a>
      {motion.playing && <ForestEntrance onSkip={motion.skip} />}
      <aside className="live-sidebar">
        <a
          href="#home"
          className="live-brand"
          onClick={(e) => {
            e.preventDefault();
            navigate("home");
          }}
        >
          <BrandLogo />
        </a>
        <p className="live-sidebar-caption">EasyRep WORKSPACE</p>
        <nav aria-label="주 메뉴">
          {tabs.map((item) => (
            <button
              key={item.id}
              aria-current={location.view === item.id ? "page" : undefined}
              onClick={() => navigate(item.id)}
            >
              <item.icon size={21} aria-hidden="true" />
              {item.label}
            </button>
          ))}
        </nav>
        <nav className="live-secondary-nav" aria-label="안내 메뉴">
          <button aria-current={location.view === "presentation" ? "page" : undefined} onClick={() => navigate("presentation")}><BookOpen size={21} aria-hidden="true" />발표 자료</button>
        </nav>
        <div className="live-sidebar-bottom">
          <span>{session.user.name}</span>
          <small>{session.user.roleLabel}</small>
          <a href="/profile/">내 계정</a>
          <button onClick={motion.replay} disabled={motion.reduced}>
            숲 다시 보기
          </button>
        </div>
      </aside>
      <main className="live-main" id="live-content">
        <header className="live-header">
          <div className="live-header-title">
            <span className="live-mobile-brand"><BrandLogo variant="icon" decorative /></span>
            <div>
              <span className="live-eyebrow">{session.site.title}</span>
              <h1 ref={heading} tabIndex={-1}>{tab?.title ?? "발표 자료"}</h1>
            </div>
          </div>
          <details ref={accountMenu} className="live-account-menu" onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.currentTarget.open = false;
              e.currentTarget.querySelector("summary")?.focus();
            }
          }}>
            <summary aria-label="계정 메뉴">
              <UserRound size={20} aria-hidden="true" />
              <span>{session.user.name}</span>
              <ChevronDown size={16} aria-hidden="true" />
            </summary>
            <div className="live-account-popover">
              <strong>{session.user.name}</strong>
              <small>{session.user.roleLabel}</small>
              <a href="/profile/">내 계정</a>
              <a href="/manage/">{managementLabels[session.user.role]}</a>
              <form action="/logout/" method="post" onSubmit={() => {
                try { Object.keys(sessionStorage).filter((key) => key.startsWith("habitatos:care-draft:")).forEach((key) => sessionStorage.removeItem(key)); } catch { /* Logout must work without storage. */ }
              }}>
                <input type="hidden" name="csrfmiddlewaretoken" value={session.csrfToken} />
                <button type="submit">로그아웃</button>
              </form>
            </div>
          </details>
        </header>
        <div className="live-body">
          <div className="live-presentation-entry"><button aria-current={location.view === "presentation" ? "page" : undefined} onClick={() => navigate("presentation")}><BookOpen size={18} aria-hidden="true" />발표 자료</button></div>
          {savedCare && <Notice>관리 기록을 저장했습니다. <button onClick={() => setSavedCare(false)}>닫기</button></Notice>}
          {session.site.notice && <Notice>{session.site.notice}</Notice>}
          {(connectionError || list.error) && (
            <Notice className="live-connection-notice">
              <CircleAlert size={19} aria-hidden="true" />
              <span><strong>{connectionError || list.error}</strong>
                {list.data && <span>마지막 조회값입니다. 현재 상태는 확인되지 않았습니다.</span>}
                {list.updatedAt && <time dateTime={list.updatedAt}>조회 성공 {dateTime(list.updatedAt)} KST</time>}
              </span>
              <button onClick={refreshLiveQueries} disabled={list.refreshing || list.offline}>
                {list.refreshing ? "확인 중…" : "다시 확인"}
              </button>
            </Notice>
          )}
          {location.view === "presentation" ? (
            <Suspense fallback={<Empty>발표 자료를 불러오고 있습니다.</Empty>}>
              <Presentation onReturn={() => navigate(returnRoute.current.view, returnRoute.current.id, { section: returnRoute.current.section, mode: returnRoute.current.mode })} />
            </Suspense>
          ) : !list.data ? (
            !list.error && !connectionError &&
            <Empty>사육장 정보를 확인하고 있습니다.</Empty>
          ) : location.id && !cage ? (
            <Panel title="사육장을 찾을 수 없습니다.">
              <p>주소가 변경되었거나 조회 권한이 없습니다. 접근 가능한 사육장을 다시 선택하세요.</p>
              <button onClick={() => navigate("home", "")}>사육장 목록으로</button>
            </Panel>
          ) : !cage ? (
            <Panel title="사육장 등록 대기">
              <Empty>등록되거나 배정된 사육장이 없습니다.</Empty>
              <a href={session.user.role === "owner" ? "/manage/enclosures/new/" : "/manage/"} className="live-button">
                {session.user.role === "owner" ? "센서 없이 사육장 등록" : managementLabels[session.user.role]}
              </a>
            </Panel>
          ) : (
            <>
              {list.data.truncated && (
                <Notice>
                  사육장 200개까지 표시합니다. 전체 등록 정보는 관리 화면에서
                  확인하세요.
                </Notice>
              )}
              <div className="live-context">
                <label>
                  사육장
                  <select
                    value={cage.id}
                    onChange={(e) => navigate(location.view, e.target.value)}
                  >
                    {sensorCages.length > 0 && <optgroup label="현재 센서 수신">
                      {sensorCages.map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.name}
                        </option>
                      ))}
                    </optgroup>}
                    {pendingCages.length > 0 && <optgroup label="확인 필요">
                      {pendingCages.map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.name}
                        </option>
                      ))}
                    </optgroup>}
                    {simulatedCages.length > 0 && <optgroup label="가상 데이터">
                      {simulatedCages.map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.name} · 가상 데이터
                        </option>
                      ))}
                    </optgroup>}
                  </select>
                </label>
                <div>
                  {awaitingDevice ? <span className="live-source">장치 연결 전</span> : <Badge cage={cage} />}
                  <button className="live-refresh" onClick={refreshLiveQueries} disabled={list.refreshing || list.offline} aria-label="현재 화면 데이터 새로고침">
                    <RefreshCw size={16} aria-hidden="true" />
                    <span className="live-refresh-label">{list.refreshing ? "조회 중" : "새로고침"}</span>
                  </button>
                  <details className="live-context-actions" key={`${location.view}-${cage.id}`}><summary>사육장 작업 <ChevronDown size={14} aria-hidden="true" /></summary><div>
                    <EnclosureViewer cage={cage} session={session} />
                    {session.user.role === "owner" && <GatewayCameraViewer session={session} />}
                    {session.user.role === "owner" && <a className="live-button" href="/manage/enclosures/new/">사육장 등록</a>}
                  </div></details>
                </div>
              </div>
              {measurement?.warning && (
                <Notice className="live-status-notice">
                  <CircleAlert size={19} aria-hidden="true" />
                  <span>
                    <strong>{measurement.label}</strong>
                    <span className="live-status-message">{measurement.message}</span>
                    {cage.sampledAt && <time dateTime={cage.sampledAt}>마지막 측정 {dateTime(cage.sampledAt)} KST</time>}
                  </span>
                </Notice>
              )}
              {location.view === "home" && (
                <>
                  <div className="live-fleet" id="live-fleet" data-expanded={showAllCages} role="group" aria-label="사육장 선택">
                    {homeCages.map((item) => (
                      <button
                        key={item.id}
                        className="live-cage-card"
                        aria-pressed={item.id === cage.id}
                        onClick={() => navigate("home", item.id)}
                      >
                        <div className="live-cage-title">
                          <EnclosurePhoto cage={item} thumbnail />
                          <span>
                            <strong>{item.name}</strong>
                          </span>
                        </div>
                        {!item.sampledAt && item.gateway.status === "unregistered" ? <p className="live-note">{item.species || "개체 정보 미입력"} · 장치 연결 전</p> : <><Badge cage={item} /><EnvironmentSummary cage={item} /></>}
                        <span className="live-mobile-measured">
                          {item.sampledAt ? <>측정 <time dateTime={item.sampledAt}>{dateTime(item.sampledAt)} KST</time></> : item.gateway.status === "unregistered" ? "센서 없이 등록된 사육장" : "아직 측정값을 받지 않았습니다."}
                        </span>
                      </button>
                    ))}
                  </div>
                  {(cage.spatialLayout || nonSensorCageCount > 0) && <div className="live-home-actions">
                    {cage.spatialLayout && <button onClick={() => navigate("environment", cage.id, { mode: "spatial" })}>
                      <Layers3 size={18} aria-hidden="true" />공간 온도
                    </button>}
                    {nonSensorCageCount > 0 && (
                      <button className="live-fleet-toggle" aria-expanded={showAllCages} aria-controls="live-fleet" onClick={() => setShowAllCages(!showAllCages)}>
                        {showAllCages ? "현재 수신 사육장만 보기" : `확인 필요 ${nonSensorCageCount}개 보기`}
                        <ChevronDown size={17} aria-hidden="true" />
                      </button>
                    )}
                  </div>}
                  {!cage.sampledAt && cage.gateway.status === "unregistered" ? <div className="live-grid">
                    <CareRecords key={cage.id} cage={cage} session={session} compact onOpen={() => navigate("history", cage.id, { section: "care" })} />
                    <Panel title="장치 연결 전">
                      <p>사진과 사육 관리 기록을 먼저 등록할 수 있습니다.</p>
                      <dl className="live-description"><dt>사육 개체·종</dt><dd>{cage.species || "미입력"}</dd><dt>설치 위치</dt><dd>{cage.location || "미입력"}</dd></dl>
                      <button onClick={() => navigate("management")}>사육장 정보 보기</button>
                    </Panel>
                  </div> : <div className="live-home-layout">
                    <HistoryOverview
                      key={`home-chart-${cage.id}`}
                      cage={cage}
                      compact
                      onOpen={() => navigate("history", cage.id, { section: "overview" })}
                    />
                    <div className="live-home-side">
                      <Panel
                        title="장치 상태"
                        icon={CircuitBoard}
                        action={
                          <button onClick={() => navigate("control")}>
                            제어 화면
                          </button>
                        }
                      >
                        <DeviceRows cage={cage} />
                      </Panel>
                      <CareRecords key={`recent-${cage.id}`} cage={cage} session={session} compact onOpen={() => navigate("history", cage.id, { section: "care" })} />
                    </div>
                  </div>}
                </>
              )}
              {location.view === "environment" && (
                <EnvironmentWorkspace key={cage.id} cage={cage} mode={location.mode} onModeChange={(mode) => navigate("environment", cage.id, { mode })} onManagement={() => navigate("management")} />
              )}
              {location.view === "control" && <Control cage={cage} />}
              {location.view === "history" && (
                <RecordWorkspace key={cage.id} cage={cage} session={session} section={location.section} onSectionChange={(section) => navigate("history", cage.id, { section })} />
              )}
              {location.view === "management" && (
                <Management cage={cage} session={session} />
              )}
              <footer className="live-footer">
                <span>
                  <Activity size={14} /> 서버 조회 {dateTime(list.data.asOf)}{" "}
                  KST
                </span>
                <span>
                  Pi 통신 {dateTime(cage.gateway.lastReceivedAt)} · 센서 측정{" "}
                  {dateTime(cage.sampledAt)}
                </span>
              </footer>
            </>
          )}
        </div>
      </main>
      <nav className="live-mobile-nav" aria-label="모바일 메뉴">
        {tabs.map((item) => (
          <button
            key={item.id}
            aria-current={location.view === item.id ? "page" : undefined}
            onClick={() => navigate(item.id)}
          >
            <item.icon size={22} aria-hidden="true" />
            <span>{item.label}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}
