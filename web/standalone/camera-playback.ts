/** One camera's recovery lifecycle; transport and clocks are injected for tests. */
export type PlaybackStatus = "connecting" | "playing" | "retrying" | "waiting" | "paused" | "play-required" | "denied" | "unsupported";
export type CameraTransport = { destroy(): void; suspend?(): void; resume?(): void };
export type CameraFault = { status?: number; fatal?: boolean; network?: boolean };
export type CameraPlaybackOptions = {
  connect: (ready: () => void, failed: (fault: CameraFault) => void) => CameraTransport;
  probe: (signal: AbortSignal) => Promise<number>;
  onStatus: (status: PlaybackStatus) => void;
  onPauseIntent: (paused: boolean) => void;
  initiallyPaused?: boolean;
  hidden?: () => boolean;
  now?: () => number;
  setTimer?: (fn: () => void, delay: number) => number;
  clearTimer?: (timer: number) => void;
};

export const CAMERA_RECOVERY = {
  retryDelays: [1000, 2000, 4000, 8000], probeInterval: 30000,
  probeTimeout: 8000, stalledAfter: 8000, stableAfter: 20000,
} as const;

export function createCameraPlayback(video: HTMLVideoElement, options: CameraPlaybackOptions) {
  const now = options.now ?? (() => performance.now());
  const hidden = options.hidden ?? (() => document.hidden);
  const setTimer = options.setTimer ?? ((fn, delay) => window.setTimeout(fn, delay));
  const clearTimer = options.clearTimer ?? ((timer) => window.clearTimeout(timer));
  let disposed = false, wantsPlay = !options.initiallyPaused, blocked = false, denied = false;
  let changingSource = false, attempting = false, generation = 0, attempts = 0;
  let transport: CameraTransport | undefined, abort: AbortController | undefined;
  let retryTimer: number | undefined, watchdog: number | undefined, probeTimer: number | undefined;
  let frameCallback: number | undefined, lastFrames = -1, lastProgress = now(), stableSince: number | undefined;
  let status: PlaybackStatus | undefined;
  function show(next: PlaybackStatus) {
    if (!disposed && status !== next) { status = next; options.onStatus(next); }
  }
  function clear(name: "retry" | "watchdog" | "probe") {
    const id = name === "retry" ? retryTimer : name === "watchdog" ? watchdog : probeTimer;
    if (id !== undefined) clearTimer(id);
    if (name === "retry") retryTimer = undefined;
    else if (name === "watchdog") watchdog = undefined;
    else probeTimer = undefined;
  }
  function cancelAttempt() {
    ++generation; abort?.abort(); abort = undefined; attempting = false; clear("probe");
  }
  function stopSource() {
    changingSource = true;
    transport?.destroy(); transport = undefined;
  }
  function eligible() { return !disposed && wantsPlay && !blocked && !denied && !hidden(); }
  function queueRecovery() {
    if (!eligible() || retryTimer !== undefined || attempting) return;
    stableSince = undefined;
    const delay = CAMERA_RECOVERY.retryDelays[Math.max(0, attempts - 1)] ?? CAMERA_RECOVERY.probeInterval;
    show(attempts <= CAMERA_RECOVERY.retryDelays.length ? "retrying" : "waiting");
    retryTimer = setTimer(() => { retryTimer = undefined; void attempt(); }, delay);
  }
  function failed(fault: CameraFault = {}) {
    if (!eligible()) return;
    stableSince = undefined;
    if (fault.status === 401 || fault.status === 403) {
      denied = true; clear("retry"); clear("watchdog"); cancelAttempt(); stopSource(); show("denied");
      return;
    }
    // Network errors include nonfatal manifest/fragment404,503 and timeouts.
    // Short buffer stalls are handled by decoded-frame progress, not each event.
    if (fault.network || fault.fatal) {
      stopSource(); queueRecovery();
    }
  }
  async function playMedia() {
    if (!eligible() || !transport) return;
    const mine = generation;
    try { await video.play(); }
    catch (error) {
      if (mine !== generation || !eligible()) return;
      if (error instanceof Error && error.name === "AbortError") return;
      if (!(error instanceof Error) || error.name !== "NotAllowedError") { failed({ fatal: true }); return; }
      blocked = true; clear("retry"); clear("watchdog"); transport?.suspend?.(); show("play-required");
    }
  }
  async function attempt() {
    if (!eligible() || attempting) return;
    clear("retry"); stopSource(); attempting = true; ++attempts;
    lastProgress = now(); stableSince = undefined; lastFrames = -1;
    show(attempts === 1 ? "connecting" : "retrying");
    const mine = ++generation, controller = new AbortController(); abort = controller;
    probeTimer = setTimer(() => controller.abort(), CAMERA_RECOVERY.probeTimeout);
    try {
      const code = await options.probe(controller.signal);
      if (disposed || mine !== generation || !eligible()) return;
      if (code === 401 || code === 403) { denied = true; show("denied"); return; }
      if (code !== 200) throw new Error("camera unavailable");
      // Construction must not reset attempts: only sustained decoded frames do.
      let constructing = true;
      let initialFault: CameraFault | undefined;
      transport = options.connect(() => queueMicrotask(() => {
        if (mine === generation) void playMedia();
      }), (fault) => {
        if (mine !== generation) return;
        if (constructing) initialFault = fault; else failed(fault);
      });
      constructing = false;
      if (initialFault) failed(initialFault);
      if (transport) armWatchdog();
    } catch {
      // Abort on pause/unmount/visibility is intentional; timeouts retry below.
    } finally {
      if (mine === generation) {
        clear("probe"); abort = undefined; attempting = false;
        if (!transport && !denied) queueRecovery();
      }
    }
  }
  function progress(frames: number) {
    if (!Number.isFinite(frames)) return;
    if (!eligible() || video.paused || video.seeking) { lastFrames = frames; stableSince = undefined; return; }
    if (frames > lastFrames) {
      if (lastFrames < 0) { lastFrames = frames; lastProgress = now(); return; }
      lastFrames = frames; lastProgress = now();
      stableSince ??= now();
      show("playing");
      if (now() - stableSince >= CAMERA_RECOVERY.stableAfter) attempts = 0;
    } else if (frames < lastFrames) { lastFrames = frames; stableSince = undefined; }
  }
  function observeFrame(_time: number, metadata: VideoFrameCallbackMetadata) {
    if (disposed) return;
    progress(metadata.presentedFrames);
    frameCallback = video.requestVideoFrameCallback(observeFrame);
  }
  function armWatchdog() {
    clear("watchdog");
    if (!eligible()) return;
    watchdog = setTimer(() => {
      watchdog = undefined;
      if (!eligible()) return;
      if (!video.requestVideoFrameCallback) {
        const quality = video.getVideoPlaybackQuality?.();
        const decoded = quality ? quality.totalVideoFrames - quality.droppedVideoFrames
          : (video as HTMLVideoElement & { webkitDecodedFrameCount?: number }).webkitDecodedFrameCount;
        if (decoded !== undefined) progress(decoded);
      }
      if (video.seeking) { stableSince = undefined; lastProgress = now(); }
      else if (now() - lastProgress >= CAMERA_RECOVERY.stalledAfter) {
        stopSource(); queueRecovery(); return;
      }
      armWatchdog();
    }, 1000);
  }
  function pause() {
    wantsPlay = false; blocked = false; options.onPauseIntent(true);
    stableSince = undefined; clear("retry"); clear("watchdog"); cancelAttempt();
    transport?.suspend?.(); show("paused");
  }
  function play() {
    if (disposed) return;
    const wasBlocked = blocked;
    wantsPlay = true; blocked = false; denied = false; options.onPauseIntent(false);
    lastProgress = now(); stableSince = undefined;
    if (wasBlocked && transport) { transport.resume?.(); void playMedia(); armWatchdog(); }
    else { cancelAttempt(); clear("retry"); void attempt(); }
  }
  function onPlay() {
    changingSource = false;
    if (!wantsPlay || blocked) play();
  }
  function onPause() {
    if (!changingSource && !video.ended && !video.error) pause();
  }
  function onSeek() { stableSince = undefined; lastProgress = now(); }
  function onError() { failed({ fatal: true }); }
  function visibility() {
    stableSince = undefined; lastProgress = now();
    if (hidden()) { clear("retry"); clear("watchdog"); if (attempting) cancelAttempt(); }
    else if (eligible()) {
      if (transport) { if (video.paused) void playMedia(); armWatchdog(); }
      else queueRecovery();
    }
  }
  video.addEventListener("play", onPlay); video.addEventListener("pause", onPause);
  video.addEventListener("seeking", onSeek); video.addEventListener("seeked", onSeek);
  video.addEventListener("error", onError);
  if (video.requestVideoFrameCallback) frameCallback = video.requestVideoFrameCallback(observeFrame);
  if (wantsPlay) void attempt(); else show("paused");
  return {
    play, visibility,
    retry() { if (wantsPlay && !blocked) { denied = false; cancelAttempt(); clear("retry"); void attempt(); } },
    destroy() {
      disposed = true; cancelAttempt(); clear("retry"); clear("watchdog"); stopSource();
      if (frameCallback !== undefined) video.cancelVideoFrameCallback(frameCallback);
      video.removeEventListener("play", onPlay); video.removeEventListener("pause", onPause);
      video.removeEventListener("seeking", onSeek); video.removeEventListener("seeked", onSeek);
      video.removeEventListener("error", onError);
      video.removeAttribute("src"); video.load();
    },
  };
}
