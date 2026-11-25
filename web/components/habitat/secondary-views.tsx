"use client";

import { useState } from "react";
import {
  Box,
  Camera,
  X,
  Droplets,
  Fan,
  Sun,
  CircleAlert,
  CircleCheck,
  ChevronRight,
  Clock3,
  LockKeyhole,
  Radio,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Search,
  RotateCcw,
  Wifi,
  WifiOff,
} from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Switch } from "@/components/ui/switch";
import { Sheet, SheetTrigger, SheetContent, SheetHeader, SheetTitle, SheetDescription, SheetClose } from "@/components/ui/sheet";
import { type DemoState } from "@/lib/habitat/demo";
import {
  enclosures,
  cameraLabels,
  type Enclosure,
} from "@/lib/habitat/enclosures";
import {
  commandStatuses,
  devices,
  getReadings,
  getRecords,
  filterRecords,
  DEMO_NOW,
  receivedAt,
  timeLabel,
  type RecordEntry,
  type RecordFilters,
} from "@/lib/habitat/model";

export function ControlView({ state }: { state: DemoState }) {
  const offline = state === "offline";
  return (
    <div className="secondary-layout control-workspace">
      <section className="panel control-policy">
        <div className="policy-heading">
          <h2><SlidersHorizontal size={16} /> 운영 정책</h2>
          <span className="neutral-badge">미연동</span>
        </div>
        <dl className="policy-summary">
          <div><dt>환경 기준</dt><dd>기준 미설정</dd></div>
          <div><dt>요청한 정책</dt><dd>없음</dd></div>
          <div><dt>게이트웨이 적용</dt><dd>미확인</dd></div>
        </dl>
      </section>
      <section className="panel control-panel">
        <div className="panel-heading">
          <h2>장치별 제어</h2>
          <span className="control-note" id="control-unavailable">
            <LockKeyhole size={14} /> 실제 제어 미연동
          </span>
        </div>
        <div className="control-devices">
          {devices.map((device) => {
            const Icon =
              device.id === "mist" ? Droplets : device.id === "fan" ? Fan : Sun;
            return (
              <div key={device.id} className="control-device">
                <div className="control-device-heading">
                  <div className="control-device-identity">
                    <span className="control-device-icon">
                      <Icon size={19} aria-hidden="true" />
                    </span>
                    <h3>
                      {device.name}
                      <span className="muted">{device.model}</span>
                    </h3>
                  </div>
                  <span className={`neutral-badge ${offline ? "warning-text" : ""}`}>
                    {offline ? "현재 미확인" : device.state}
                  </span>
                </div>
                <dl className="requested-applied">
                  <div>
                    <dt>최근 요청</dt>
                    <dd>{offline ? "미확인" : device.request}</dd>
                  </div>
                  <div>
                    <dt>실제 적용</dt>
                    <dd>{offline ? "미확인" : device.applied}</dd>
                  </div>
                </dl>
                <div className="disabled-controls">
                  <button className="button" disabled aria-label={`${device.name} 작동 요청`} aria-describedby="control-unavailable">
                    작동
                  </button>
                  <button className="button" disabled aria-label={`${device.name} 중지 요청`} aria-describedby="control-unavailable">
                    중지
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </section>
      <section className="panel command-results">
        <div className="panel-heading">
          <div>
            <h2>최근 명령 결과</h2>
          </div>
        </div>
        {getRecords(state)
          .filter((record) => record.kind === "명령")
          .map((record) => (
            <div className="command-result-row" key={record.id}>
              <div>
                <h3>{record.title}</h3>
                <p>
                  {record.target} · {timeLabel(record.time)}
                </p>
              </div>
              <span className="neutral-badge">{record.status}</span>
            </div>
          ))}
        <details className="command-status-guide">
          <summary>명령 상태 안내</summary>
          <div className="command-statuses">
            {commandStatuses.map((status) => (
              <span key={status} className="neutral-badge">{status}</span>
            ))}
          </div>
        </details>
        {offline && (
          <p className="panel-message">
            <Clock3 size={15} /> 마지막 수신 이후의 명령 결과는 미확인입니다.
          </p>
        )}
      </section>
    </div>
  );
}

export function HistoryView({
  state,
  onDetail,
  gateway,
}: {
  state: DemoState;
  gateway?: string;
  onDetail: (record: RecordEntry) => void;
}) {
  const [filter, setFilter] = useState<NonNullable<RecordFilters["kind"]>>("전체");
  const [query, setQuery] = useState("");
  const [minutes, setMinutes] = useState(0);
  const [status, setStatus] = useState("전체");
  const matching = filterRecords(getRecords(state, gateway), { query, minutes, status });
  const filtered = matching.filter((record) => filter === "전체" || record.kind === filter);
  const hasFilters = filter !== "전체" || query !== "" || minutes !== 0 || status !== "전체";
  function resetFilters() {
    setFilter("전체");
    setQuery("");
    setMinutes(0);
    setStatus("전체");
  }
  return (
    <section className="panel history-panel">
      <div className="panel-heading">
        <div>
          <h2>기록 목록</h2>
          <p>2026.09.15 {timeLabel(DEMO_NOW)} 기준 · KST</p>
        </div>
        <span className="neutral-badge">데모 기록</span>
      </div>
      <div className="history-filters" role="search" aria-label="운영 기록 검색">
        <label className="history-search">
          <span>검색</span>
          <span className="history-search-input">
            <Search size={17} aria-hidden="true" />
            <input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="대상·내용 검색" aria-label="기록 검색" />
          </span>
        </label>
        <label>
          <span>기간</span>
          <select aria-label="기록 기간" value={minutes} onChange={(event) => setMinutes(Number(event.target.value))}>
            <option value={0}>전체 기간</option>
            <option value={60}>최근 1시간</option>
            <option value={30}>최근 30분</option>
          </select>
        </label>
        <label>
          <span>처리 상태</span>
          <select aria-label="기록 처리 상태" value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="전체">전체 상태</option>
            {["조치 필요", "복구됨", "실행 완료", "변경됨"].map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
      </div>
      <Tabs value={filter} onValueChange={(value) => setFilter(value as NonNullable<RecordFilters["kind"]>)}>
        <div className="history-toolbar">
          <TabsList className="history-tabs" aria-label="기록 필터">
            {["전체", "이상 이벤트", "명령", "설정 변경"].map((label) => (
              <TabsTrigger key={label} value={label} aria-label={label}>
                {label}
                <span className="history-filter-count" aria-hidden="true">
                  {matching.filter((record) => label === "전체" || record.kind === label).length}
                </span>
              </TabsTrigger>
            ))}
          </TabsList>
          <div className="history-result-tools">
            <p className="history-result-count" aria-live="polite">{filtered.length}건 · 최신순</p>
            <button className="button history-reset" onClick={resetFilters} disabled={!hasFilters}>
              <RotateCcw size={15} aria-hidden="true" /> 초기화
            </button>
          </div>
        </div>
        <TabsContent value={filter}>
          <Table className="history-table" aria-label={`${filter} 운영 기록`}>
            <TableHeader>
              <TableRow>
                <TableHead scope="col" className="history-time">발생시각</TableHead>
                <TableHead scope="col" className="history-target">대상</TableHead>
                <TableHead scope="col" className="history-content">기록 내용</TableHead>
                <TableHead scope="col" className="history-result">처리 상태</TableHead>
                <TableHead scope="col" className="history-ack">사용자 확인</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((record) => {
                const needsAction = record.status === "조치 필요";
                const StatusIcon = needsAction ? CircleAlert : ["복구됨", "실행 완료", "변경됨"].includes(record.status) ? CircleCheck : Clock3;
                return (
                  <TableRow key={record.id} className="history-entry">
                    <TableCell className="history-time">
                      <time dateTime={new Date(record.time).toISOString()}>{timeLabel(record.time)}</time>
                    </TableCell>
                    <TableCell className="history-target">{record.target}</TableCell>
                    <TableCell className="history-content">
                      <span className="history-kind">{record.kind}</span>
                      <button className="history-detail-link" onClick={() => onDetail(record)} aria-label={`${record.summary} · ${record.target} 상세 보기`}>
                        <span>{record.summary}</span>
                        <ChevronRight size={16} aria-hidden="true" />
                      </button>
                    </TableCell>
                    <TableCell className="history-result">
                      <span className="history-mobile-label">처리 상태</span>
                      <span className={`history-status ${needsAction ? "needs-action" : ""}`}>
                        <StatusIcon size={15} aria-hidden="true" />{record.status}
                      </span>
                    </TableCell>
                    <TableCell className="history-ack">
                      <span className="history-mobile-label">사용자 확인</span>
                      <span className={record.kind !== "이상 이벤트" ? "muted" : ""}>
                        {record.kind === "이상 이벤트" ? record.acknowledged ? "확인함" : "미확인" : "해당 없음"}
                      </span>
                    </TableCell>
                  </TableRow>
                );
              })}
              {filtered.length === 0 && (
                <TableRow className="history-empty"><TableCell colSpan={5}>
                  <strong>조건에 맞는 기록이 없습니다.</strong>
                  <p>검색어나 필터를 바꿔보세요.</p>
                  {hasFilters && <button className="button" onClick={resetFilters}>필터 초기화</button>}
                </TableCell></TableRow>
              )}
            </TableBody>
          </Table>
        </TabsContent>
      </Tabs>
      <p className="panel-footnote">
        <CircleAlert size={14} /> 사용자 확인 여부와 문제 복구 여부는 별도로
        기록됩니다.
      </p>
    </section>
  );
}

export function ManagementView({
  state,
  enclosure = enclosures[0],
  onAccounts,
}: {
  state: DemoState;
  enclosure?: Enclosure;
  onAccounts?: () => void;
}) {
  const readings = getReadings(state, enclosure.sensors);
  return (
    <div className="management-grid">
      <section className="panel settings-basic">
        <div className="panel-heading">
          <h2>사육장 기본 정보</h2>
          <Box size={18} aria-hidden="true" />
        </div>
        <div className="settings-body">
          <Definition label="사육장 이름" value={enclosure.name} />
          <Definition label="사육 개체" value={enclosure.species} />
          <Definition label="설치 구역" value={enclosure.location} />
          <Definition label="시간대" value="Asia/Seoul (KST)" />
          <Definition label="환경 기준" value="기준 미설정" />
        </div>
      </section>
      <section className="panel settings-gateway">
        <div className="panel-heading">
          <h2>게이트웨이 연결 정보</h2>
          {state === "offline" ? <WifiOff size={18} aria-hidden="true" /> : <Wifi size={18} aria-hidden="true" />}
        </div>
        <div className="settings-body">
          <Definition label="게이트웨이" value={enclosure.gateway} />
          <Definition label="연결 상태" value={state === "offline" ? "통신 끊김 (데모)" : "연결됨 (데모)"} />
          <Definition label="마지막 수신" value={`2026.09.15 ${timeLabel(receivedAt(state), true)}`} />
          <Definition label="실제 연결" value="미연동" />
        </div>
      </section>
      <section className="panel settings-camera">
        <div className="panel-heading">
          <h2>카메라 등록 정보</h2>
          <Camera size={18} aria-hidden="true" />
        </div>
        <div className="settings-body">
          <Definition label="카메라" value={enclosure.camera.name ?? "미설치"} />
          <Definition label="데모 상태" value={cameraLabels[enclosure.camera.state]} />
          <Definition label="실제 영상 연결" value="미연동" />
          <div className="settings-footer">
            <button className="button" disabled aria-describedby="camera-unavailable">카메라 연결</button>
            <p id="camera-unavailable">카메라 연결은 실제 연동 후 사용할 수 있습니다.</p>
          </div>
        </div>
      </section>
      <section className="panel registration-panel">
        <div className="panel-heading">
          <h2>센서·장치 등록 정보</h2>
          <Radio size={18} aria-hidden="true" />
        </div>
        <div className="settings-body">
          <Definition label="온도 센서" value={`${readings.filter((sensor) => sensor.metric === "temperature").length}개 등록`} />
          <Definition label="습도·조도 센서" value={`${readings.filter((sensor) => sensor.metric !== "temperature").length}개 등록`} />
          <Definition label="등록 장치" value="분무기 · 환기 팬 · 조명" />
          <div className="settings-footer">
            <Sheet>
              <SheetTrigger asChild>
                <button className="button">센서·설치 위치 보기</button>
              </SheetTrigger>
              <SheetContent showCloseButton={false} className="record-sheet registration-sheet">
                <SheetHeader>
                  <SheetTitle>센서·설치 위치</SheetTitle>
                  <SheetDescription>{enclosure.name} · 예시 배치</SheetDescription>
                </SheetHeader>
                <SheetClose asChild>
                  <button className="sheet-close" aria-label="센서 상세 닫기"><X size={18} aria-hidden="true" /></button>
                </SheetClose>
                {readings.length > 0 ? (
                  <div className="registered-sensors">
                    {readings.map((sensor) => (
                      <div key={sensor.id}>
                        <span>{sensor.id}</span>
                        <strong>{sensor.name}</strong>
                        <span className={sensor.status === "error" ? "warning-text" : ""}>
                          {sensor.status === "error" ? "측정 오류" : "등록됨"}
                        </span>
                      </div>
                    ))}
                  </div>
                ) : <p className="registration-empty">등록된 센서가 없습니다.</p>}
                <div className="registration-actions">
                  <button className="button" disabled aria-describedby="registration-unavailable">센서 등록</button>
                  <button className="button" disabled aria-describedby="registration-unavailable">설치 위치 편집</button>
                  <p id="registration-unavailable">등록·설치 위치 변경은 실제 연동 후 사용할 수 있습니다.</p>
                </div>
              </SheetContent>
            </Sheet>
            <p>설치 위치는 예시이며 실제 등록은 미연동입니다.</p>
          </div>
        </div>
      </section>
      <section className="panel settings-access">
        <div className="panel-heading">
          <h2>사용자 권한</h2>
          <ShieldCheck size={18} aria-hidden="true" />
        </div>
        <div className="settings-body">
          <Definition label="계정 체계" value="총괄 · 매장 관리자 · 사용자" />
          <Definition label="관리 범위" value="소속 매장 · 담당 사육장" />
          <Definition label="실제 로그인" value="미연동" />
          <div className="settings-footer"><button className="button" onClick={onAccounts}>계정·권한 관리</button></div>
        </div>
      </section>
      <section className="panel settings-alerts">
        <div className="panel-heading">
          <h2>알림 설정</h2>
          <Settings2 size={18} aria-hidden="true" />
        </div>
        <div className="settings-body">
          <div className="notification-setting">
            <h3>이상 상태 알림</h3>
            <Switch checked={false} disabled aria-label="이상 상태 푸시 알림, 연동 예정" />
          </div>
          <div className="settings-footer"><p>푸시 알림 연동 예정</p></div>
        </div>
      </section>
    </div>
  );
}
function Definition({ label, value }: { label: string; value: string }) {
  return (
    <div className="definition-row">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
