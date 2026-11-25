import { useRef, useState } from "react";

export default function PresentationVideo({ src, label }: { src: string; label: string }) {
  const video = useRef<HTMLVideoElement>(null);
  const [status, setStatus] = useState<"ready" | "loading" | "error">("ready");

  function retry() {
    setStatus("loading");
    // Keep focus on the player when the retry button disappears.
    video.current?.focus({ preventScroll: true });
    video.current?.load();
  }

  return <figure className="briefing-video" data-media-state={status}>
    <video ref={video} controls playsInline preload="metadata" src={src} aria-label={label}
      onError={() => setStatus("error")} onLoadedMetadata={() => setStatus("ready")} />
    <figcaption>
      <span role="status">원본 발표자료의 영상 · {status === "error" ? "영상을 불러오지 못했습니다." : status === "loading" ? "영상을 다시 불러오는 중입니다." : "재생 버튼으로 확인"}</span>
      {status === "error" && <button type="button" onClick={retry}>영상 다시 불러오기</button>}
    </figcaption>
  </figure>;
}
