import { SlidersHorizontal, CircuitBoard, History } from "lucide-react";
import {
  commandLabels,
  dateTime,
  deviceLabel,
  type Cage,
  type Command,
} from "./live-data";
import { useLiveQuery } from "./use-live-query";
import { Panel, Empty, Notice, DeviceRows } from "./live-panels";

export function Control({ cage }: { cage: Cage }) {
  const commands = useLiveQuery<{ items: Command[] }>(
    `/api/enclosures/${encodeURIComponent(cage.id)}/commands/`,
  );
  return (
    <div className="live-grid">
      <Panel title="적용 상태" icon={SlidersHorizontal}>
        <dl className="live-description">
          <dt>Pi 보고 모드</dt>
          <dd>
            {cage.mode === "auto"
              ? "자동"
              : cage.mode === "manual"
                ? "수동"
                : "미수신"}
          </dd>
          <dt>환경 기준</dt>
          <dd>기준 미설정</dd>
          <dt>원격 명령</dt>
          <dd>미연동</dd>
        </dl>
        <p className="live-note">
          화면의 버튼은 장치에 명령을 보내지 않습니다.
        </p>
      </Panel>
      <Panel title="장치가 보고한 상태" icon={CircuitBoard}>
        <DeviceRows cage={cage} />
        <button disabled>원격 제어 · 연동 예정</button>
      </Panel>
      <Panel title="최근 명령 결과" icon={History} className="live-span">
        {commands.error ? (
          <Notice>{commands.error}</Notice>
        ) : !commands.data?.items.length ? (
          <Empty>아직 수신한 명령 기록이 없습니다.</Empty>
        ) : (
          <div className="live-command-table">
            <div className="live-table-head">
              <span>장치·시각</span>
              <span>요청 값</span>
              <span>처리 결과</span>
            </div>
            {commands.data.items.map((command) => (
              <div key={command.command_id}>
                <span>
                  <strong>{deviceLabel(command.actuator_id)}</strong>
                  <small>{dateTime(command.created_at)}</small>
                </span>
                <span data-label="요청 값">
                  {command.action === "on"
                    ? `${command.duration_s}초 켜기`
                    : "끄기"}
                </span>
                <span data-label="처리 결과">
                  <strong>
                    {commandLabels[command.status] || command.status}
                  </strong>
                  <small>{command.reason || "—"}</small>
                </span>
              </div>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}
