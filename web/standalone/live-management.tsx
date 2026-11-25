import { ArrowUpRight, Box, Wifi, UserRound, ShieldCheck } from "lucide-react";
import { managementLabels, type AuthSession } from "../lib/habitat/session";
import { dateTime, gatewayLabels, measurementStatus, operationalStatus, type Cage } from "./live-data";
import { AppInstallPanel } from "./app-install";
import { Panel } from "./live-panels";
import { EnclosurePhoto } from "./enclosure-photo";
import { EnclosureViewer } from "./enclosure-viewer";

export function Management({
  cage,
  session,
}: {
  cage: Cage;
  session: AuthSession;
}) {
  const dataStatus = operationalStatus(cage);
  return (
    <div className="live-grid live-management-grid">
      <Panel title="사육장 정보" icon={Box}>
        <dl className="live-description">
          <dt>이름</dt>
          <dd>{cage.name}</dd>
          <dt>등록 매장명</dt>
          <dd>{cage.store}</dd>
          <dt>데이터 구분</dt>
          <dd>{dataStatus.label}<small>{dataStatus.detail}</small></dd>
          <dt>사육 개체·종</dt><dd>{cage.species || "미입력"}</dd>
          <dt>설치 위치</dt><dd>{cage.location || "미입력"}</dd>
          <dt>Pi 사육장 ID</dt>
          <dd>{cage.cageId || "장치 연결 전"}</dd>
          <dt>카메라</dt>
          <dd>미연동</dd>
        </dl>
        {session.user.role === "owner" && <a className="live-button" href={`/manage/enclosures/${encodeURIComponent(cage.id)}/`}>사육장 정보 수정</a>}
      </Panel>
      <Panel title="대표 사진" icon={Box} action={<EnclosureViewer key={cage.id} cage={cage} session={session} label="크게 보기" />}>
        <EnclosurePhoto cage={cage} />
        <div className="live-photo-caption">
          <span>{cage.photo ? "등록 사진 · 실시간 영상 아님" : "사진이 등록되지 않았습니다."}</span>
          {session.user.role === "owner" && (
            <a className="live-button" href={`/manage/enclosures/${encodeURIComponent(cage.id)}/photo/`}>
              {cage.photo ? "사진 변경" : "사진 등록"}
            </a>
          )}
        </div>
        {cage.photo && <p className="live-note">등록 {dateTime(cage.photo.updatedAt)} KST</p>}
        {!cage.photo && session.user.role !== "owner" && <p className="live-note">사진 등록은 총괄 관리자에게 요청하세요.</p>}
      </Panel>
      <Panel title="Pi 수신 상태" icon={Wifi}>
        <dl className="live-description">
          <dt>Pi ID</dt>
          <dd>{cage.gateway.id || "미등록"}</dd>
          <dt>Pi 통신</dt>
          <dd>{gatewayLabels[cage.gateway.status]}<small>{dateTime(cage.gateway.lastReceivedAt)}</small></dd>
          <dt>센서 측정</dt>
          <dd>{measurementStatus(cage).label}<small>{dateTime(cage.sampledAt)}</small></dd>
          <dt>이력에 저장된 측정</dt>
          <dd>{dateTime(cage.historyReceipt?.sampledAt ?? null)}</dd>
        </dl>
        <details className="live-reception-details">
          <summary>수신 상세</summary>
          <dl className="live-description">
            <dt>이력 서버 수신</dt><dd>{dateTime(cage.historyReceipt?.receivedAt ?? null)}</dd>
            <dt>센서 구성</dt><dd>{cage.sensors.length ? `${cage.sensors.length}개 수신` : "미수신"}</dd>
          </dl>
          <p className="live-note">Pi 통신, 센서 측정, 이력 저장 시각은 서로 다릅니다. 시간은 KST 기준입니다.</p>
        </details>
        {(cage.stale && cage.sampledAt || cage.historyReceipt?.behindCurrent) && <div className="live-reception-notice" role="status">
          <strong>{cage.historyReceipt?.behindCurrent ? "현재값과 이력 수신을 확인하세요" : "새 측정값을 기다리고 있습니다"}</strong>
          {cage.stale && cage.sampledAt && <p>Pi 통신과 별개로 센서 측정값이 오래됐습니다. 센서 노드의 전원·연결을 확인하세요.</p>}
          {cage.historyReceipt?.behindCurrent && <p>최신 현재값에 해당하는 이력이 아직 도착하지 않았습니다. 계속되면 Pi의 이벤트 전송 대기열을 확인하세요.</p>}
        </div>}
      </Panel>
      <Panel title="내 계정·권한" icon={UserRound}>
        <dl className="live-description">
          <dt>이름</dt>
          <dd>{session.user.name}</dd>
          <dt>역할</dt>
          <dd>{session.user.roleLabel}</dd>
          <dt>소속</dt>
          <dd>{session.user.storeName}</dd>
        </dl>
        <a className="live-button" href="/profile/">
          내 계정 수정
        </a>
      </Panel>
      <Panel title={managementLabels[session.user.role]} icon={ShieldCheck}>
        <p>{session.user.role === "owner"
          ? "전체 매장과 계정 권한, 사이트·Pi 수신 설정을 관리합니다."
          : session.user.role === "manager"
            ? "소속 매장의 사용자 계정과 담당 사육장을 관리합니다."
            : "내 계정과 배정된 사육장을 확인합니다."}</p>
        <a className="live-button" href="/manage/">
          {session.user.role === "user" ? "내 배정 확인" : "관리 화면 열기"} <ArrowUpRight size={16} />
        </a>
        <p className="live-note">
          {session.user.role === "user"
            ? "배정 변경은 소속 관리자에게 요청하세요."
            : session.user.role === "manager"
              ? "매장·사이트·Pi 설정 변경은 총괄 관리자가 담당합니다."
              : "계정 권한을 변경하면 해당 계정의 기존 접속이 종료됩니다."}
        </p>
      </Panel>
      <AppInstallPanel />
    </div>
  );
}
