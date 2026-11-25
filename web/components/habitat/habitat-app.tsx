"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { flushSync } from "react-dom";
import {
  Box,
  LayoutDashboard,
  ChartNoAxesCombined,
  SlidersHorizontal,
  History,
  Settings2,
  Wifi,
  WifiOff,
  ArrowUpRight,
  ChevronRight,
  FlaskConical,
  Download,
  Layers,
  Sparkles,
  RotateCcw,
  X,
} from "lucide-react";
import {
  SidebarProvider,
  Sidebar,
  SidebarHeader,
  SidebarContent,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
  SidebarFooter,
} from "@/components/ui/sidebar";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import {
  demoStates,
  type DemoState,
  type Metric,
  type View,
} from "@/lib/habitat/demo";
import {
  fullTime,
  getReadings,
  receivedAt,
  timeLabel,
  getSamples,
  makeCsv,
  type RecordEntry,
} from "@/lib/habitat/model";
import type { EnvironmentSelection } from "./environment-chart";
import { EnvironmentChartLoader } from "./environment-chart-loader";
import {
  ActiveAlert,
  DevicePanel,
  EnvironmentSummary,
  RecentRecords,
  SensorMap,
} from "./overview";
import { ControlView, HistoryView, ManagementView } from "./secondary-views";

import {
  enclosures as demoEnclosures,
  type Enclosure,
} from "@/lib/habitat/enclosures";
import { EnclosureMedia } from "./enclosure-media";
import { EnclosureDashboard } from "./enclosure-dashboard";
import { BrandLogo } from "./brand-logo";
import { AccountManagement } from "./account-management";
import type { AuthSession } from "@/lib/habitat/session";
import { demoAccounts } from "@/lib/habitat/accounts";
import { ForestEntrance, useForestMotion } from "./forest-motion";

const navigation = [
  {
    id: "home",
    label: "홈",
    title: "전체 사육장",
    icon: LayoutDashboard,
  },
  {
    id: "environment",
    label: "환경",
    title: "환경 상세",
    icon: ChartNoAxesCombined,
  },
  {
    id: "control",
    label: "제어",
    title: "운영 및 장치 제어",
    icon: SlidersHorizontal,
  },
  {
    id: "history",
    label: "기록",
    title: "운영 기록",
    icon: History,
  },
  {
    id: "management",
    label: "관리",
    title: "관리",
    icon: Settings2,
  },
] as const;

// Internal views share one document. Avoid fragment navigation events that can
// trigger the host router, and retain its history metadata for Back/Forward.
function writeViewHash(route: string) {
  const hash = `#${route}`;
  if (window.location.hash !== hash) window.history.pushState(window.history.state, "", hash);
}

type ModelTool = {
  name: string;
  description: string;
  inputSchema: object;
  annotations: { readOnlyHint: boolean };
  execute: (input: unknown) => unknown;
};
type ModelContext = {
  registerTool: (
    tool: ModelTool,
    options: { signal: AbortSignal },
  ) => void | Promise<void>;
};

export function HabitatApp({ authSession, availableEnclosures = demoEnclosures, publicDemo = false }: { authSession?: AuthSession; availableEnclosures?: Enclosure[]; publicDemo?: boolean } = {}) {
  const enclosures = availableEnclosures;
  const getEnclosure = (id: string) => enclosures.find(item => item.id === id);
  const forestMotion = useForestMotion();
  const [managementTab, setManagementTab] = useState("enclosure");
  const [accounts, setAccounts] = useState(demoAccounts);
  const [accountPreviewId, setAccountPreviewId] = useState(demoAccounts[0].id);
  const [view, setView] = useState<View>("home");
  const [enclosureId, setEnclosureId] = useState(enclosures[0].id);
  const enclosure = getEnclosure(enclosureId) ?? enclosures[0];
  const [states, setStates] = useState<Record<string, DemoState>>(() =>
    Object.fromEntries(enclosures.map((item) => [item.id, item.defaultState])),
  );
  const state = states[enclosure.id];
  const enclosureRef = useRef(enclosure);
  enclosureRef.current = enclosure;
  const setState = useCallback(
    (next: DemoState) =>
      setStates((previous) => ({
        ...previous,
        [enclosureRef.current.id]: next,
      })),
    [],
  );
  const [photos, setPhotos] = useState<Record<string, string>>({});
  const [mediaTab, setMediaTab] = useState("photo");
  const photoUrls = useRef<Record<string, string>>({});
  useEffect(
    () => () => {
      Object.values(photoUrls.current).forEach((url) =>
        URL.revokeObjectURL(url),
      );
    },
    [],
  );
  function changePhoto(file: File | null) {
    const id = enclosure.id;
    const old = photoUrls.current[id];
    if (old) URL.revokeObjectURL(old);
    const next = { ...photoUrls.current };
    if (file) next[id] = URL.createObjectURL(file);
    else delete next[id];
    photoUrls.current = next;
    setPhotos(next);
  }
  const [selection, setSelection] = useState<EnvironmentSelection>({
    metric: "temperature",
    period: 6,
    sensor: "all",
  });
  const [source, setSource] = useState("measured");
  const [detail, setDetail] = useState<RecordEntry | null>(null);
  const detailTrigger = useRef<HTMLElement | null>(null);
  function openRecordDetail(record: RecordEntry) {
    detailTrigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setDetail(record);
  }
  const [exportMessage, setExportMessage] = useState("");
  const focusCamera = useRef(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const firstView = useRef(true);
  const stateRef = useRef(state);
  stateRef.current = state;
  const current = navigation.find((item) => item.id === view) ?? {
    title: "사육장 상세",
  };
  const offline = state === "offline";
  const showingAccounts = view === "management" && managementTab === "accounts";
  const relatedSensor = enclosure.sensors.find((sensor) =>
    detail?.target.startsWith(`${sensor.id} ·`),
  );

  const navigate = useCallback((next: View) => {
    setView(next);
    writeViewHash(next === "home" ? "home" : `${next}/${enclosureRef.current.id}`);
    window.scrollTo({ top: 0, behavior: "instant" });
  }, []);
  useEffect(() => {
    const syncRoute = () => {
      const [route = "home", id] = (window.location.hash.slice(1) || "home").split("/");
      if (
        navigation.some((item) => item.id === route) ||
        route === "enclosure"
      ) {
        if (id && !getEnclosure(id)) {
          setView("home");
          window.history.replaceState(window.history.state, "", "#home");
          return;
        }
        if (id) setEnclosureId(id);
        setView(route as View);
      }
    };
    syncRoute();
    window.addEventListener("hashchange", syncRoute);
    window.addEventListener("popstate", syncRoute);
    return () => {
      window.removeEventListener("hashchange", syncRoute);
      window.removeEventListener("popstate", syncRoute);
    };
  }, []);
  useEffect(() => {
    document.title = `${current.title} · EasyRep`;
    if (firstView.current) firstView.current = false;
    else headingRef.current?.focus({ preventScroll: true });
  }, [view, current.title, enclosureId]);
  useEffect(() => {
    setSelection({ metric: "temperature", period: 6, sensor: "all" });
    setDetail(null);
    setSource("measured");
  }, [enclosureId]);
  useEffect(() => {
    if (!focusCamera.current || view !== "enclosure") return;
    const frame = requestAnimationFrame(() => {
      focusCamera.current = false;
      const panel = document.getElementById("enclosure-media");
      panel?.scrollIntoView({ block: "start", behavior: "instant" });
      panel?.focus({ preventScroll: true });
    });
    return () => cancelAnimationFrame(frame);
  }, [view, enclosureId, mediaTab]);

  useEffect(() => {
    setExportMessage("");
  }, [state, selection]);

  useEffect(() => {
    const context = (document as Document & { modelContext?: ModelContext })
      .modelContext;
    if (!context?.registerTool) return;
    const lifecycle = new AbortController();
    const tools: ModelTool[] = [
      {
        name: "set_demo_state",
        description:
          "Change the EasyRep demo scenario only. Does not connect or operate hardware.",
        inputSchema: {
          type: "object",
          properties: {
            state: {
              type: "string",
              enum: demoStates.map((item) => item.value),
            },
          },
          required: ["state"],
          additionalProperties: false,
        },
        annotations: { readOnlyHint: false },
        execute(input) {
          if (
            !input ||
            typeof input !== "object" ||
            Object.keys(input).length !== 1 ||
            !("state" in input) ||
            !demoStates.some((item) => item.value === input.state)
          )
            throw new Error("Invalid demo state");
          const next = input.state as DemoState;
          flushSync(() => setState(next));
          return { state: next, demo: true };
        },
      },
      {
        name: "read_demo_environment",
        description:
          "Read the selected demo scenario with per-sensor measurement times and validity.",
        inputSchema: {
          type: "object",
          properties: {},
          additionalProperties: false,
        },
        annotations: { readOnlyHint: true },
        execute(input) {
          if (!input || typeof input !== "object" || Object.keys(input).length)
            throw new Error("Expected an empty object");
          return {
            demo: true,
            state: stateRef.current,
            enclosure: enclosureRef.current.name,
            sensors: getReadings(
              stateRef.current,
              enclosureRef.current.sensors,
            ),
          };
        },
      },
    ];
    for (const tool of tools) {
      try {
        Promise.resolve(
          context.registerTool(tool, { signal: lifecycle.signal }),
        ).catch((error) =>
          console.warn("EasyRep tool registration failed", error),
        );
      } catch (error) {
        console.warn("EasyRep tool registration failed", error);
      }
    }
    return () => lifecycle.abort();
  }, []);

  const openMetric = (metric: Metric) => {
    setSelection((previous) => ({ ...previous, metric, sensor: "all" }));
    setSource("measured");
    navigate("environment");
  };
  const openEnvironment = () => {
    setSource("measured");
    navigate("environment");
  };
  const changeState = (value: DemoState) => {
    setState(value);
    setDetail(null);
  };
  const onManage = () => navigate("management");
  function downloadCsv() {
    if (state === "unregistered") return;
    const blob = new Blob(
      [
        makeCsv(
          state,
          selection.period,
          selection.metric,
          selection.sensor,
          enclosure.sensors,
          enclosure.name,
        ),
      ],
      { type: "text/csv;charset=utf-8;" },
    );
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `EasyRep-${enclosure.id}-demo-${selection.metric}-${selection.period}h-${state}.csv`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    setExportMessage(
      `데모 CSV가 준비되었습니다 · ${selection.period}시간 · ${getSamples(state, selection.period, enclosure.sensors).length}개 측정시각`,
    );
  }
  function openEnclosure(item: Enclosure, camera = false) {
    focusCamera.current = camera;
    setEnclosureId(item.id);
    setMediaTab(camera ? "camera" : "photo");
    setView("enclosure");
    writeViewHash(`enclosure/${item.id}`);
    if (!camera) window.scrollTo({ top: 0, behavior: "instant" });
  }
  const activeNavigation = view === "enclosure" ? "home" : view;
  const effectiveHomeSelection =
    selection.metric === "light"
      ? { ...selection, metric: "temperature" as Metric, sensor: "all" }
      : selection;

  return (
    <SidebarProvider
      className="habitat-workspace"
      data-forest-entering={forestMotion.playing ? "true" : undefined}
      style={{ "--sidebar-width": "220px" } as CSSProperties}
    >
      {forestMotion.playing && <ForestEntrance onSkip={forestMotion.skip} />}
      <a
        className="skip-link"
        href="#main-content"
        onClick={(event) => {
          event.preventDefault();
          const main = document.getElementById("main-content");
          main?.focus({ preventScroll: true });
          main?.scrollIntoView({ block: "start" });
        }}
      >
        본문으로 이동
      </a>
      <Sidebar collapsible="none" className="habitat-sidebar">
        <SidebarHeader className="brand">
          <BrandLogo />
        </SidebarHeader>
        <SidebarContent>
          <div className="sidebar-label">현재 사육장</div>
          <select
            className="enclosure-picker"
            aria-label="현재 사육장 선택"
            value={enclosure.id}
            onChange={(event) =>
              openEnclosure(getEnclosure(event.target.value)!)
            }
          >
            {enclosures.map((item) => (
              <option key={item.id} value={item.id}>
                {item.number} · {item.species}
              </option>
            ))}
          </select>

          <nav aria-label="주 메뉴">
            <SidebarMenu>
              {navigation.map(({ id, label, icon: Icon }) => (
                <SidebarMenuItem key={id}>
                  <SidebarMenuButton
                    className="nav-item"
                    isActive={activeNavigation === id}
                    onClick={() => navigate(id)}
                    aria-current={activeNavigation === id ? "page" : undefined}
                  >
                    <Icon />
                    <span>{label}</span>
                    {activeNavigation === id && (
                      <ChevronRight className="nav-arrow" />
                    )}
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </nav>
          <div className="sidebar-forest" aria-hidden="true" />
        </SidebarContent>
        <SidebarFooter className="sidebar-footer">
          <div className="sidebar-note">
            <FlaskConical size={15} />
            <span>프로토타입 · 장치 미연동</span>
          </div>
        </SidebarFooter>
      </Sidebar>
      <div className="app-shell">
        <header className="topbar">
          <div className="enclosure-title">
            <BrandLogo variant="icon" decorative />
            <span>
              {view === "home" || showingAccounts ? "EasyRep 워크스페이스" : enclosure.name}
            </span>
          </div>
          <div className="topbar-status">
            {view !== "home" && !showingAccounts && (
              <div className="connection-stack">
                <span
                  className={offline ? "connection warning-text" : "connection"}
                >
                  {offline ? <WifiOff size={15} /> : <Wifi size={15} />}{" "}
                  {offline ? "게이트웨이 통신 끊김" : "게이트웨이 연결됨"}
                </span>
                <span className="receipt-time">
                  마지막 수신 {timeLabel(receivedAt(state), true)}
                </span>
              </div>
            )}
            <button
              className="forest-replay"
              onClick={forestMotion.replay}
              disabled={forestMotion.playing || forestMotion.reduced}
              aria-label="숲 진입 연출 다시 보기"
              title={forestMotion.reduced
                ? "움직임 줄이기 설정이 적용되어 있습니다"
                : forestMotion.playing ? "숲 연출 재생 중" : "숲 진입 연출 다시 보기"}
            >
              <RotateCcw size={14} />

            </button>
            <span className="demo-badge">데모 데이터</span>
            {publicDemo && <a className="session-account-link" href="/login/">관리자 로그인</a>}
            {authSession && <a className="session-account-link" href="/profile/">{authSession.user.name}<span>{authSession.user.roleLabel}</span></a>}
            {authSession && <form action="/logout/" method="post"><input type="hidden" name="csrfmiddlewaretoken" value={authSession.csrfToken}/><button className="session-logout" type="submit">로그아웃</button></form>}
          </div>
        </header>
        <main id="main-content" tabIndex={-1} className={`page-content page-${view}`}>
          {publicDemo && <p className="session-notice">로그인 없이 둘러보는 데모입니다. 센서값·기록·계정은 예시이며, 화면 변경은 실제 운영에 반영되지 않습니다.</p>}
          {authSession?.site.notice && <p className="session-notice">{authSession.site.notice}</p>}
          <div className="page-heading">
            <div className="page-title-group">
              <h1 ref={headingRef} tabIndex={-1}>
                {current.title}
              </h1>
              {view !== "home" && !showingAccounts && (
                <div className="enclosure-context">
                  <button onClick={() => navigate("home")}>전체 사육장</button>
                  <ChevronRight size={13} />
                  <select
                    aria-label="사육장 전환"
                    value={enclosure.id}
                    onChange={(event) => {
                      const id = event.target.value;
                      setEnclosureId(id);
                      writeViewHash(`${view}/${id}`);
                    }}
                  >
                    {enclosures.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name}
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </div>
            {view !== "home" && !showingAccounts && (
              <div className="demo-control">
                <span>
                  <FlaskConical size={14} /> 데모 상태
                </span>
                <Select
                  value={state}
                  onValueChange={(value) => changeState(value as DemoState)}
                >
                  <SelectTrigger aria-label="데모 상태">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {demoStates.map((item) => (
                      <SelectItem key={item.value} value={item.value}>
                        {item.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
          </div>
          {(view === "enclosure" || view === "environment") && (
            <ActiveAlert
              gateway={enclosure.gateway}
              state={state}
              onDetail={openRecordDetail}
            />
          )}
          {view === "home" && (
            <EnclosureDashboard
              enclosures={enclosures}
              states={states}
              photos={photos}
              onOpen={openEnclosure}
            />
          )}
          {view === "enclosure" && (
            <>
              <EnvironmentSummary
                key={`summary-${enclosure.id}`}
                sensorSet={enclosure.sensors}
                state={state}
                onMetric={openMetric}
                onManage={onManage}
              />
              <div className={`dashboard-grid ${state === "unregistered" ? "without-history" : ""}`}>
                {state !== "unregistered" && (
                  <div className="home-chart">
                    <EnvironmentChartLoader
                      key={`chart-${enclosure.id}`}
                      sensorSet={enclosure.sensors}
                      state={state}
                      selection={effectiveHomeSelection}
                      onChange={setSelection}
                      onDetail={openEnvironment}
                      onManage={onManage}
                    />
                  </div>
                )}
                <EnclosureMedia
                  key={enclosure.id}
                  enclosure={enclosure}
                  state={state}
                  photo={photos[enclosure.id]}
                  tab={mediaTab}
                  onTab={setMediaTab}
                  onPhoto={changePhoto}
                  onManage={onManage}
                />
                <DevicePanel
                  state={state}
                  onControl={() => navigate("control")}
                />
                <RecentRecords
                  gateway={enclosure.gateway}
                  state={state}
                  onAll={() => navigate("history")}
                  onDetail={openRecordDetail}
                />
              </div>
              {state !== "unregistered" && (
                <button
                  className="mobile-location-link detail-location-link"
                  onClick={openEnvironment}
                >
                  <Box size={17} />
                  <span>센서 위치와 개별 측정값 확인</span>
                  <ArrowUpRight size={15} />
                </button>
              )}
            </>
          )}
          {view === "environment" && (
            <Tabs
              value={source}
              onValueChange={setSource}
              className="environment-view"
            >
              <div className="environment-toolbar">
                <TabsList
                  variant="line"
                  className="source-tabs"
                  aria-label="데이터 구분"
                >
                  <TabsTrigger value="measured">
                    <ChartNoAxesCombined size={15} />
                    실측
                  </TabsTrigger>
                  <TabsTrigger value="spatial">
                    <Layers size={15} />
                    공간 추정<span>예정</span>
                  </TabsTrigger>
                  <TabsTrigger value="prediction">
                    <Sparkles size={15} />
                    AI 예측<span>예정</span>
                  </TabsTrigger>
                </TabsList>
                <button
                  className="button csv-button"
                  onClick={downloadCsv}
                  disabled={state === "unregistered" || source !== "measured"}
                  title="선택한 항목·기간·센서의 데모 데이터"
                >
                  <Download size={14} />
                  CSV 내려받기
                </button>
              </div>
              <p className="export-message" role="status">
                {exportMessage}
              </p>
              <TabsContent value="measured">
                <EnvironmentSummary
                  key={`summary-${enclosure.id}`}
                  sensorSet={enclosure.sensors}
                  state={state}
                  selectedMetric={selection.metric}
                  onMetric={(metric) =>
                    setSelection((previous) => ({
                      ...previous,
                      metric,
                      sensor: "all",
                    }))
                  }
                  onManage={onManage}
                />
                {state !== "unregistered" && (
                  <div className="environment-grid">
                    <EnvironmentChartLoader
                      key={`chart-${enclosure.id}`}
                      sensorSet={enclosure.sensors}
                      state={state}
                      selection={selection}
                      onChange={setSelection}
                      detailed
                      onManage={onManage}
                    />
                    <SensorMap
                      key={`map-${enclosure.id}`}
                      sensorSet={enclosure.sensors}
                      state={state}
                      selected={selection.sensor}
                      metric={selection.metric}
                      onSelect={(sensor) =>
                        setSelection((previous) => ({ ...previous, sensor }))
                      }
                      detailed
                    />
                  </div>
                )}
              </TabsContent>
              <TabsContent value="spatial">
                <ComingSoon kind="spatial" />
              </TabsContent>
              <TabsContent value="prediction">
                <ComingSoon kind="prediction" />
              </TabsContent>
            </Tabs>
          )}
          {view === "control" && <ControlView state={state} />}
          {view === "history" && (
            <HistoryView
              key={enclosure.id}
              gateway={enclosure.gateway}
              state={state}
              onDetail={openRecordDetail}
            />
          )}
          {view === "management" && (
            <Tabs value={managementTab} onValueChange={setManagementTab} className="management-workspace">
              <TabsList className="management-tabs" aria-label="관리 항목">
                <TabsTrigger value="enclosure">사육장 설정</TabsTrigger>
                <TabsTrigger value="accounts">계정·권한</TabsTrigger>
              </TabsList>
              <TabsContent value="enclosure"><ManagementView enclosure={enclosure} state={state} onAccounts={() => setManagementTab("accounts")} /></TabsContent>
              <TabsContent value="accounts">{authSession ? <section className="panel session-management"><h2>{authSession.user.roleLabel}</h2><p>{authSession.user.name} · {authSession.user.storeName}</p><p>로그인한 계정의 권한으로 관리합니다.</p><div><a className="button primary" href="/manage/">{authSession.user.role === "owner" ? "사이트·계정 관리" : authSession.user.role === "manager" ? "소속 사용자 관리" : "내 권한 확인"}</a><a className="button" href="/profile/">내 계정</a></div></section> : <><p className="session-notice">계정 화면 미리보기 · 실제 계정은 <a href="https://habitatos.kro.kr/login/">운영 사이트</a>에서 관리합니다.</p><AccountManagement accounts={accounts} onChange={setAccounts} actorId={accountPreviewId} onActorChange={setAccountPreviewId} /></>}</TabsContent>
            </Tabs>
          )}
          <footer className="page-footer">
            <span>{enclosure.date} KST</span>
          </footer>
        </main>
      </div>
      <nav className="mobile-nav" aria-label="모바일 주 메뉴">
        {navigation.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => navigate(id)}
            aria-current={activeNavigation === id ? "page" : undefined}
          >
            <Icon size={21} />
            <span>{label}</span>
          </button>
        ))}
      </nav>
      <Sheet
        open={!!detail}
        onOpenChange={(open) => {
          if (!open) setDetail(null);
        }}
      >
        <SheetContent showCloseButton={false} className="record-sheet" onCloseAutoFocus={(event) => {
          event.preventDefault();
          const target = detailTrigger.current?.isConnected ? detailTrigger.current : headingRef.current;
          target?.focus({ preventScroll: true });
        }}>
          <SheetHeader>
            <span className="eyebrow">기록 상세 · 데모</span>
            <SheetTitle>{detail?.title}</SheetTitle>
            <SheetDescription>
              {detail?.target} · {detail && fullTime(detail.time)}
            </SheetDescription>
          </SheetHeader>
          <SheetClose asChild>
            <button className="sheet-close" aria-label="상세 닫기">
              <X size={18} />
            </button>
          </SheetClose>
          {detail && (
            <div className="sheet-body">
              <p>{detail.detail}</p>
              <div className="definition-row">
                <span>처리 상태</span>
                <strong>{detail.status}</strong>
              </div>
              {detail.kind === "이상 이벤트" && (
                <>
                  <div className="definition-row">
                    <span>사용자 확인</span>
                    <strong>{detail.acknowledged ? "확인함" : "미확인"}</strong>
                  </div>
                  <div className="definition-row">
                    <span>문제 복구</span>
                    <strong>{detail.recovered ? "복구됨" : "복구 전"}</strong>
                  </div>
                  <p className="sheet-note">
                    사용자 확인과 실제 문제 복구는 별도 상태입니다.
                  </p>
                </>
              )}
              {relatedSensor && (
                <button
                  className="button"
                  onClick={() => {
                    setSelection((previous) => ({
                      ...previous,
                      metric: relatedSensor.metric,
                      sensor: relatedSensor.id,
                    }));
                    setDetail(null);
                    openEnvironment();
                  }}
                >
                  센서 실측 확인 <ArrowUpRight size={15} />
                </button>
              )}
              <button
                className="button primary"
                onClick={() => {
                  setDetail(null);
                  navigate(detail.kind === "명령" ? "control" : "history");
                }}
              >
                관련 기록 보기 <ArrowUpRight size={15} />
              </button>
            </div>
          )}
        </SheetContent>
      </Sheet>
    </SidebarProvider>
  );
}
function ComingSoon({ kind }: { kind: "spatial" | "prediction" }) {
  const Icon = kind === "spatial" ? Layers : Sparkles;
  return (
    <section className="panel coming-soon">
      <Icon size={26} />
      <span className="neutral-badge">연동 예정</span>
      <h2>{kind === "spatial" ? "공간 추정" : "AI 미래 예측"}</h2>
      <p>
        {kind === "spatial"
          ? "센서 사이 공간의 환경 분포를 추정하는 기능입니다."
          : "실측 이력을 바탕으로 앞으로의 환경 변화를 예측하는 기능입니다."}
      </p>
      <p className="muted">아직 연결된 결과가 없습니다.</p>
    </section>
  );
}
