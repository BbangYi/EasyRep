import { useState } from "react";
import { ImageOff, ImageIcon, RefreshCw } from "lucide-react";
import type { Cage } from "./live-data";

export function EnclosurePhoto({ cage, thumbnail = false }: { cage: Cage; thumbnail?: boolean }) {
  const src = thumbnail ? cage.photo?.thumbnailUrl : cage.photo?.url;
  return src ? (
    <PhotoImage key={src} src={src} name={cage.name} thumbnail={thumbnail} />
  ) : (
    <span className={thumbnail ? "live-photo-thumb" : "live-photo-preview"}>
      <span className="live-photo-placeholder"><ImageIcon size={22} aria-hidden="true" /><span>사진 없음</span></span>
    </span>
  );
}

function PhotoImage({ src, name, thumbnail }: { src: string; name: string; thumbnail: boolean }) {
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [attempt, setAttempt] = useState(0);
  return (
    <span className={thumbnail ? "live-photo-thumb" : "live-photo-preview"} aria-busy={status === "loading"}>
      {status !== "error" && (
        <img key={attempt} src={src} alt={`${name} 대표 사진`} loading={thumbnail ? "lazy" : "eager"} decoding="async"
          onLoad={() => setStatus("ready")} onError={() => setStatus("error")} />
      )}
      {status === "loading" && <span className="live-photo-loading" role={thumbnail ? undefined : "status"}>사진 불러오는 중</span>}
      {status === "error" && (
        <span className="live-photo-placeholder">
          <ImageOff size={22} aria-hidden="true" /><span>{thumbnail ? "사진 확인 불가" : "사진을 불러오지 못했습니다."}</span>
          {!thumbnail && <button type="button" className="live-photo-retry" onClick={() => { setAttempt(attempt + 1); setStatus("loading"); }}><RefreshCw size={15} aria-hidden="true" />다시 불러오기</button>}
        </span>
      )}
    </span>
  );
}
