"use client";

import { useEffect, useRef, useState, type ChangeEvent } from "react";
import {
  Camera,
  CameraOff,
  ImageIcon,
  Info,
  Maximize2,
  Upload,
  WifiOff,
  X,
} from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { type Enclosure, cameraLabels } from "@/lib/habitat/enclosures";
import { type DemoState } from "@/lib/habitat/demo";
import { EnclosurePhoto } from "./enclosure-dashboard";

type Props = {
  enclosure: Enclosure;
  state: DemoState;
  photo?: string;
  tab: string;
  onTab: (tab: string) => void;
  onPhoto: (file: File | null) => void;
  onManage: () => void;
};

/** Camera status is independent of gateway status. This prototype contains no live feed. */
export function EnclosureMedia({
  enclosure,
  state,
  photo,
  tab,
  onTab,
  onPhoto,
  onManage,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState("");
  const pendingImage = useRef<{ image: HTMLImageElement; url: string } | null>(
    null,
  );
  const [loadingPhoto, setLoadingPhoto] = useState(false);
  useEffect(
    () => () => {
      if (pendingImage.current) {
        pendingImage.current.image.onload = null;
        pendingImage.current.image.onerror = null;
        URL.revokeObjectURL(pendingImage.current.url);
      }
    },
    [],
  );
  const [expanded, setExpanded] = useState(false);
  const camera = enclosure.camera;
  const installed = camera.state !== "not-installed";
  const offline = camera.state === "offline";
  const canExpand =
    tab === "photo"
      ? !!(photo || enclosure.photo)
      : installed && !!enclosure.photo;
  function pickPhoto(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
      setError("JPG, PNG, WebP 사진을 선택해 주세요.");
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      setError("10MB 이하의 사진을 선택해 주세요.");
      return;
    }
    setLoadingPhoto(true);
    const url = URL.createObjectURL(file);
    const image = new Image();
    pendingImage.current = { image, url };
    image.onload = () => {
      URL.revokeObjectURL(url);
      pendingImage.current = null;
      setLoadingPhoto(false);
      setError("");
      onPhoto(file);
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      pendingImage.current = null;
      setLoadingPhoto(false);
      setError("사진을 읽을 수 없습니다. 다른 파일을 선택해 주세요.");
    };
    image.src = url;
  }
  function frame(enlarged = false) {
    if (tab === "camera" && !installed)
      return (
        <div className="camera-empty">
          <CameraOff size={32} />
          <h3>설치된 카메라가 없습니다</h3>
          <p>카메라를 연결하면 사육장 내부를 확인할 수 있습니다.</p>
          <button className="button" onClick={onManage}>
            카메라 등록 정보
          </button>
        </div>
      );
    return (
      <div className={`media-frame ${enlarged ? "enlarged-frame" : ""}`}>
        <EnclosurePhoto
          enclosure={enclosure}
          src={tab === "photo" ? photo : undefined}
        />
        {tab === "camera" && (
          <div className="camera-frame-label">
            {offline ? <WifiOff size={14} /> : <Camera size={14} />}
            <span>
              {offline
                ? "마지막 프레임 예시 · 오래된 화면"
                : "카메라 화면 예시 · 정지 이미지"}
            </span>
          </div>
        )}
        {tab === "camera" && (
          <span className="frame-time">예시 시각 {camera.lastFrameAt} KST</span>
        )}
        {tab === "photo" && (
          <span className="photo-kind">
            {photo
              ? "내 사진 · 이번 세션만"
              : enclosure.photo
                ? "대표 사진 · 예시"
                : "사진 미등록"}
          </span>
        )}
      </div>
    );
  }
  return (
    <section
      className="panel enclosure-media"
      id="enclosure-media"
      tabIndex={-1}
      aria-label="사육장 사진과 카메라"
    >
      <div className="panel-heading">
        <div>
          <h2>사육장 보기</h2>
        </div>
        {canExpand && (
          <button
            className="media-expand"
            onClick={() => setExpanded(true)}
            aria-label={
              tab === "camera" ? "카메라 예시 확대" : "대표 사진 확대"
            }
          >
            <Maximize2 size={16} />
            <span>확대</span>
          </button>
        )}
      </div>
      <Tabs value={tab} onValueChange={onTab}>
        <TabsList className="media-tabs" aria-label="사육장 보기 방식">
          <TabsTrigger value="photo">
            <ImageIcon size={15} />
            대표 사진
          </TabsTrigger>
          <TabsTrigger value="camera">
            <Camera size={15} />
            카메라{!installed && <span>미설치</span>}
          </TabsTrigger>
        </TabsList>
        <TabsContent value="photo">
          {frame()}
          <div className="media-actions">
            <button
              className="button"
              disabled={loadingPhoto}
              onClick={() => inputRef.current?.click()}
            >
              <Upload size={14} />
              {loadingPhoto ? "사진 확인 중" : "사진 변경"}
            </button>
            {photo && (
              <button
                className="text-button"
                onClick={() => {
                  onPhoto(null);
                  setError("");
                }}
              >
                기본 사진
              </button>
            )}
            <input
              ref={inputRef}
              type="file"
              accept="image/jpeg,image/png,image/webp"
              onChange={pickPhoto}
              hidden
              aria-label="대표 사진 선택"
            />
          </div>
          <p className="media-note">
            최대 10MB · 새로고침 시 초기화
          </p>
          {error && (
            <p role="alert" className="media-note warning-text">
              {error}
            </p>
          )}
        </TabsContent>
        <TabsContent value="camera">
          {frame()}
          {installed && (
            <div className="camera-details">
              <div>
                <span>{camera.name}</span>
                <strong className={offline ? "warning-text" : ""}>
                  {offline ? <WifiOff size={13} /> : <Camera size={13} />}{" "}
                  {cameraLabels[camera.state]}
                </strong>
              </div>
              <p>
                <Info size={13} /> 실시간 영상 미연동 · 정지 이미지 예시
              </p>
            </div>
          )}
          {state === "offline" && (
            <p className="media-note warning-text">
              게이트웨이 통신 끊김 · 센서도 오래된 데이터입니다.
            </p>
          )}
        </TabsContent>
      </Tabs>
      {enclosure.photo && !(tab === "photo" && photo) && (
        <details className="media-credit">
          <summary>사진 출처</summary>
          <p>
            예시 사진 ·{" "}
            <a href={enclosure.photo.source} target="_blank" rel="noreferrer">
              {enclosure.photo.credit}
            </a>{" "}
            ·{" "}
            <a href={enclosure.photo.licenseUrl} target="_blank" rel="noreferrer">
              {enclosure.photo.license}
            </a>{" "}
            · 비율에 맞춰 표시
          </p>
        </details>
      )}
      <Dialog open={expanded} onOpenChange={setExpanded}>
        <DialogContent className="media-dialog" showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>{enclosure.name}</DialogTitle>
            <DialogDescription>
              {tab === "photo"
                ? "대표 사진"
                : "카메라 화면 예시 · 실시간 영상 아님"}
            </DialogDescription>
          </DialogHeader>
          <DialogClose asChild>
            <button className="sheet-close" aria-label="확대 화면 닫기">
              <X size={18} />
            </button>
          </DialogClose>
          {frame(true)}
        </DialogContent>
      </Dialog>
    </section>
  );
}
