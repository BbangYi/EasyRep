"use client";

import { useState } from "react";
import {
  ArrowUpRight,
  Camera,
  CameraOff,
  CheckCheck,
  CircleAlert,
  Clock3,
  Droplets,
  ImageOff,
  LayoutGrid,
  Search,
  Thermometer,
  WifiOff,
} from "lucide-react";
import {
  enclosures as demoEnclosures,
  cameraLabels,
  needsAttention,
  stateLabels,
  type Enclosure,
} from "@/lib/habitat/enclosures";
import { type DemoState } from "@/lib/habitat/demo";
import {
  formatValue,
  getReadings,
  receivedAt,
  summarize,
  timeLabel,
} from "@/lib/habitat/model";

export function EnclosurePhoto({
  enclosure,
  src,
}: {
  enclosure: Enclosure;
  src?: string;
}) {
  const [failed, setFailed] = useState<string | null>(null);
  const image = src ?? enclosure.photo?.src;
  if (!image || failed === image)
    return (
      <div className="enclosure-photo-empty">
        <ImageOff size={27} />
        <span>{image ? "사진을 불러올 수 없습니다" : "등록된 사진 없음"}</span>
      </div>
    );
  return (
    <img
      decoding="async"
      className="enclosure-photo"
      src={image}
      style={{ objectPosition: src ? "50% 50%" : enclosure.photo?.position }}
      alt={src ? `${enclosure.name}의 직접 선택한 사진` : enclosure.photo!.alt}
      onError={() => setFailed(image)}
    />
  );
}

export function EnclosureDashboard({
  enclosures = demoEnclosures,
  states,
  photos,
  onOpen,
}: {
  enclosures?: Enclosure[];
  states: Record<string, DemoState>;
  photos: Record<string, string>;
  onOpen: (enclosure: Enclosure, camera?: boolean) => void;
}) {
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const needsCheck = enclosures.filter((item) =>
    needsAttention(states[item.id]),
  );
  const installed = enclosures.filter(
    (item) => item.camera.state !== "not-installed",
  );
  const visible = enclosures.filter(
    (item) =>
      (filter !== "attention" || needsAttention(states[item.id])) &&
      (filter !== "camera" || item.camera.state !== "not-installed") &&
      `${item.name} ${item.species} ${item.location}`
        .toLowerCase()
        .includes(query.trim().toLowerCase()),
  );
  return (
    <div className="enclosures-overview">
      <div className="fleet-summary" aria-label="전체 사육장 요약">
        {[
          {
            label: "전체 사육장",
            value: enclosures.length,
            icon: LayoutGrid,
            filter: "all",
          },
          {
            label: "확인 필요",
            value: needsCheck.length,
            icon: CircleAlert,
            filter: "attention",
          },
          {
            label: "카메라 설치",
            value: installed.length,
            icon: Camera,
            filter: "camera",
          },
        ].map(({ label, value, icon: Icon, filter: itemFilter }) => (
          <button
            key={label}
            onClick={() => setFilter(itemFilter)}
            className={
              itemFilter === "attention" && value ? "has-attention" : ""
            }
            aria-pressed={filter === itemFilter}
          >
            <span>
              <Icon size={17} />
              {label}
            </span>
            <strong>
              {value}
              <small>개</small>
            </strong>
          </button>
        ))}
      </div>
      <div className="fleet-toolbar">
        <div className="fleet-result-heading">
          <h2>
            {filter === "attention"
              ? "확인 필요"
              : filter === "camera" ? "카메라 설치" : "사육장 목록"}
            <span>{visible.length}</span>
          </h2>
          <span>기준 미설정</span>
        </div>
        <label className="enclosure-search">
          <Search size={16} />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label="사육장 검색"
            placeholder="이름·종·위치 검색"
          />
        </label>
      </div>
      <div className="enclosure-cards">
        {visible.map((item) => {
          const state = states[item.id];
          const readings = getReadings(state, item.sensors);
          const temperature = summarize(readings, "temperature");
          const humidity = summarize(readings, "humidity");
          const StateIcon =
            state === "offline"
              ? WifiOff
              : state === "normal"
                ? CheckCheck
                : CircleAlert;
          return (
            <article className="enclosure-card" key={item.id}>
              <button
                className="enclosure-card-photo"
                onClick={() => onOpen(item)}
                aria-label={`${item.name} 상세 보기`}
              >
                <EnclosurePhoto enclosure={item} src={photos[item.id]} />
                {(photos[item.id] || item.photo) && <span className="photo-kind">
                  {photos[item.id]
                    ? "내 사진 · 임시"
                    : item.photo
                      ? "대표 사진 · 예시"
                      : "사진 미등록"}
                </span>}
                <span className="enclosure-number">{item.number}</span>
              </button>
              <div className="enclosure-card-body">
                <div className="enclosure-card-title">
                  <div>
                    <span>{item.location}</span>
                    <h3>
                      <button onClick={() => onOpen(item)}>{item.name}</button>
                    </h3>
                  </div>
                  <ArrowUpRight size={18} />
                </div>
                <div
                  className={`enclosure-status ${needsAttention(state) ? "warning-text" : ""}`}
                >
                  <StateIcon size={14} />
                  <strong>{stateLabels[state]}</strong>
                  {needsAttention(state) && (
                    <span>
                      {state === "offline" ? "오래된 데이터" : "T3 제외 · 4개 수신"}
                    </span>
                  )}
                </div>
                <div className="enclosure-card-values">
                  <div>
                    <span>
                      <Thermometer size={14} />
                      온도 범위
                    </span>
                    <strong>
                      {formatValue(temperature.min, "temperature")}
                      {temperature.count > 0 && (
                        <> – {formatValue(temperature.max, "temperature")}</>
                      )}
                      <small>°C</small>
                    </strong>
                  </div>
                  <div>
                    <span>
                      <Droplets size={14} />
                      습도
                    </span>
                    <strong>
                      {formatValue(humidity.min, "humidity")}
                      <small>%</small>
                    </strong>
                  </div>
                </div>
              </div>
              <div className="enclosure-card-footer">
                <span>
                  <Clock3 size={12} />
                  {state === "unregistered"
                    ? "측정 데이터 없음"
                    : `수신 ${timeLabel(receivedAt(state), true)}`}
                </span>
                <button onClick={() => onOpen(item, true)}>
                  {item.camera.state === "not-installed" ? (
                    <CameraOff size={14} />
                  ) : (
                    <Camera size={14} />
                  )}{" "}
                  {cameraLabels[item.camera.state]}
                  <ArrowUpRight size={12} />
                </button>
              </div>
            </article>
          );
        })}
      </div>
      {!visible.length && (
        <div className="fleet-empty">
          <Search size={25} />
          <h3>조건에 맞는 사육장이 없습니다</h3>
          <button
            className="button"
            onClick={() => {
              setQuery("");
              setFilter("all");
            }}
          >
            전체 보기
          </button>
        </div>
      )}
      <details className="photo-credits">
        <summary>예시 사진 출처</summary>
        <p>
          실제 촬영된 개체 참고 사진이며, 등록된 사육장의 사진이나 카메라 영상이
          아닙니다. 화면 비율에 맞춰 잘라 표시합니다.
        </p>
        <ul>
          {enclosures
            .filter((item) => item.photo)
            .map((item) => (
              <li key={item.id}>
                {item.species} ·{" "}
                <a href={item.photo!.source} target="_blank" rel="noreferrer">
                  {item.photo!.credit}
                </a>{" "}
                ·{" "}
                <a
                  href={item.photo!.licenseUrl}
                  target="_blank"
                  rel="noreferrer"
                >
                  {item.photo!.license}
                </a>
              </li>
            ))}
        </ul>
      </details>
    </div>
  );
}
