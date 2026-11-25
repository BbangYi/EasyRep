import { useEffect, useRef, useState } from "react";
import { Camera, CameraOff, ImageIcon, RefreshCw } from "lucide-react";
import {
  Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger,
} from "../components/ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/ui/tabs";
import type { AuthSession } from "../lib/habitat/session";
import { dateTime, type Cage } from "./live-data";
import { useLiveQuery } from "./use-live-query";
import { EnclosurePhoto } from "./enclosure-photo";

export function EnclosureViewer({
  cage, session, label = "사진·카메라 보기",
}: { cage: Cage; session: AuthSession; label?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <button type="button" className="live-button live-media-open">
          <Camera size={17} aria-hidden="true" />{label}
        </button>
      </SheetTrigger>
      <SheetContent className="live-record-detail live-media-detail">
        <SheetHeader>
          <SheetTitle>사육장 보기</SheetTitle>
          <SheetDescription>{cage.store} · {cage.name}</SheetDescription>
        </SheetHeader>
        {open && <ViewerContent key={cage.id} enclosureId={cage.id} canEdit={session.user.role === "owner"} canControl={session.user.role !== "user"} csrfToken={session.csrfToken} />}
      </SheetContent>
    </Sheet>
  );
}

export function GatewayCameraViewer({ session }: { session: AuthSession }) {
  const [open, setOpen] = useState(false);
  return <Sheet open={open} onOpenChange={setOpen}>
    <SheetTrigger asChild><button type="button" className="live-button live-media-open"><Camera size={17} aria-hidden="true" />Pi 카메라 · CAGE-001</button></SheetTrigger>
    <SheetContent className="live-record-detail live-media-detail">
      <SheetHeader><SheetTitle>Pi 카메라</SheetTitle><SheetDescription>CAGE-001 · 천장·전면</SheetDescription></SheetHeader>
      {open && <div className="live-media-body"><CameraPanel base="/api/camera/" canControl={session.user.role === "owner"} csrfToken={session.csrfToken} /></div>}
    </SheetContent>
  </Sheet>;
}

function ViewerContent({ enclosureId, canEdit, canControl, csrfToken }: { enclosureId: string; canEdit: boolean; canControl: boolean; csrfToken: string }) {
  // Recheck current scope when opened; closing unmounts the polling query.
  const query = useLiveQuery<{ item: Cage }>(`/api/enclosures/${encodeURIComponent(enclosureId)}/`);
  const cage = query.data?.item;
  return (
    <div className="live-media-body">
      {query.error && (
        <div className="live-media-notice" role="status">
          <p>{query.error}</p>
          <button type="button" onClick={query.refresh} disabled={query.refreshing || query.offline}>
            <RefreshCw size={16} aria-hidden="true" />다시 확인
          </button>
        </div>
      )}
      {!cage ? (!query.error && <p role="status">사육장 정보를 확인하고 있습니다.</p>) : (
        <Tabs defaultValue="photo" className="live-media-tabs">
          <TabsList aria-label="사육장 보기 방식">
            <TabsTrigger value="photo"><ImageIcon size={17} aria-hidden="true" />대표 사진</TabsTrigger>
            <TabsTrigger value="camera"><Camera size={17} aria-hidden="true" />카메라</TabsTrigger>
          </TabsList>
          <TabsContent value="photo">
            <div className="live-media-stage"><EnclosurePhoto cage={cage} /></div>
            <div className="live-media-caption">
              <div>
                <strong>{cage.photo ? "등록된 대표 사진" : "대표 사진 미등록"}</strong>
                <p>{cage.photo ? "등록 시점의 정지 사진입니다." : "사육장 사진을 등록하면 이곳에서 크게 볼 수 있습니다."}</p>
                {cage.photo && <time dateTime={cage.photo.updatedAt}>등록 {dateTime(cage.photo.updatedAt)} KST</time>}
              </div>
              {canEdit && <a className="live-button" href={`/manage/enclosures/${encodeURIComponent(cage.id)}/photo/`}>{cage.photo ? "사진 변경" : "사진 등록"}</a>}
            </div>
            {!canEdit && !cage.photo && <p className="live-media-help">사진 등록은 총괄 관리자에게 요청하세요.</p>}
          </TabsContent>
          <TabsContent value="camera">
            <CameraPanel base={`/api/enclosures/${encodeURIComponent(enclosureId)}/camera/`} canControl={canControl} csrfToken={csrfToken} />
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}

type CameraFeed = { id: string; view: string; fresh: boolean; status: string; playlist: string };

function CameraPanel({ base, canControl, csrfToken }: { base: string; canControl: boolean; csrfToken: string }) {
  const query = useLiveQuery<{ cameras: CameraFeed[] }>(base, 8000);
  if (!query.data) return <div className="live-camera-empty" role="status">
    <CameraOff size={32} aria-hidden="true" />
    <strong>{query.error ? "카메라를 표시할 수 없습니다" : "카메라 확인 중"}</strong>
    <p>{query.error ?? "연결 상태를 확인하고 있습니다."}</p>
    {query.error && <button type="button" className="live-button" onClick={query.refresh}>다시 확인</button>}
  </div>;
  return <>
    <div className="live-camera-grid">
      {query.data.cameras.map((camera) => <section key={camera.id} className="live-camera-feed">
        <h3>{camera.view === "top" ? "천장" : camera.view === "front" ? "전면" : camera.view} <span>{camera.id}</span></h3>
        {camera.fresh ? <CameraVideo playlist={camera.playlist} /> : <div className="live-camera-empty" role="status">
          <CameraOff size={28} aria-hidden="true" /><strong>영상 수신 대기</strong>
          <p>영상이 다시 수신되면 자동으로 표시됩니다.</p>
        </div>}
      </section>)}
    </div>
    <IrControl base={base} canControl={canControl} csrfToken={csrfToken} />
  </>;
}

function CameraVideo({ playlist }: { playlist: string }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    let disposed = false;
    let player: { destroy: () => void } | undefined;
    async function start() {
      try {
        const { default: Hls } = await import("hls.js");
        if (disposed || !video) return;
        if (Hls.isSupported()) {
          const hls = new Hls({ liveSyncDurationCount: 2 });
          player = hls;
          hls.on(Hls.Events.ERROR, (_, detail) => {
            if (detail.fatal) setError("영상 연결이 끊겼습니다.");
          });
          hls.loadSource(playlist);
          hls.attachMedia(video);
        } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
          video.src = playlist;
        } else {
          setError("이 브라우저는 실시간 영상을 재생할 수 없습니다.");
        }
      } catch {
        if (!disposed) setError("영상 재생기를 불러오지 못했습니다.");
      }
    }
    setError("");
    void start();
    return () => { disposed = true; player?.destroy(); video.removeAttribute("src"); video.load(); };
  }, [playlist, retry]);
  return <div className="live-camera-video-wrap">
    <video ref={videoRef} controls autoPlay muted playsInline onError={() => setError("영상을 재생할 수 없습니다.")} />
    {error && <div className="live-camera-playback-error" role="status">{error}<button type="button" onClick={() => setRetry((value) => value + 1)}>다시 연결</button></div>}
  </div>;
}

function IrControl({ base, canControl, csrfToken }: { base: string; canControl: boolean; csrfToken: string }) {
  const query = useLiveQuery<{ status: string; online: boolean; remainingSeconds: number | null; error: string | null }>(base + "ir/", 8000);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  async function command(action: "on" | "off") {
    if (busy) return;
    setBusy(true);
    setNotice("");
    try {
      const response = await fetch(base + "ir/command/", {
        method: "POST", credentials: "same-origin", cache: "no-store",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
        body: JSON.stringify({ action }),
      });
      if (!response.ok) throw new Error();
      setNotice("요청을 접수했습니다. 상태를 다시 확인합니다.");
      query.refresh();
    } catch {
      setNotice("요청 결과를 확인하지 못했습니다. 현재 상태를 먼저 확인하세요.");
      query.refresh();
    } finally {
      setBusy(false);
    }
  }
  return <div className="live-ir-control">
    <div><strong>적외선 조명</strong><p>{query.data ? `장치 상태: ${query.data.status === "on" ? "켜기 요청 중" : query.data.status === "off" ? "끄기 상태" : query.data.status}` : "상태 확인 중"}</p></div>
    {canControl && query.data?.online && <div className="live-ir-actions">
      <button type="button" disabled={busy || query.data.status === "on"} onClick={() => void command("on")}>5분 켜기</button>
      <button type="button" disabled={busy || query.data.status === "off"} onClick={() => void command("off")}>끄기</button>
    </div>}
    {query.error && <p role="status">장치 상태를 확인할 수 없습니다.</p>}
    {notice && <p role="status">{notice}</p>}
  </div>;
}
