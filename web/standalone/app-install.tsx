import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Download, Smartphone } from "lucide-react";
import { Panel } from "./live-panels";

type InstallPrompt = Event & {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};
type InstallState = {
  available: boolean;
  busy: boolean;
  standalone: boolean;
  installed: boolean;
  message: string;
  install(): Promise<void>;
};
const InstallContext = createContext<InstallState | null>(null);

// Mounted before session lookup so Chromium's one-shot install event is retained.
export function AppInstallProvider({ children }: { children: ReactNode }) {
  const prompt = useRef<InstallPrompt | null>(null);
  const [available, setAvailable] = useState(false);
  const [busy, setBusy] = useState(false);
  const [standalone, setStandalone] = useState(false);
  const [installed, setInstalled] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => {
    const displayMode = window.matchMedia("(display-mode: standalone)");
    const updateMode = () =>
      setStandalone(
        displayMode.matches ||
          Boolean((navigator as Navigator & { standalone?: boolean }).standalone),
      );
    const offer = (event: Event) => {
      event.preventDefault();
      prompt.current = event as InstallPrompt;
      setAvailable(true);
    };
    const done = () => {
      prompt.current = null;
      setAvailable(false);
      setInstalled(true);
      setMessage("설치됐습니다. 홈 화면의 EasyRep 아이콘으로 열 수 있습니다.");
    };
    updateMode();
    displayMode.addEventListener("change", updateMode);
    window.addEventListener("beforeinstallprompt", offer);
    window.addEventListener("appinstalled", done);
    return () => {
      displayMode.removeEventListener("change", updateMode);
      window.removeEventListener("beforeinstallprompt", offer);
      window.removeEventListener("appinstalled", done);
    };
  }, []);
  async function install() {
    const event = prompt.current;
    if (!event || busy) return;
    prompt.current = null;
    setAvailable(false);
    setBusy(true);
    setMessage("");
    try {
      await event.prompt();
      const choice = await event.userChoice;
      // An accepted prompt is not proof that the browser finished installing.
      if (choice.outcome === "dismissed")
        setMessage("설치를 취소했습니다. 브라우저 메뉴에서 다시 설치할 수 있습니다.");
    } catch {
      setMessage("설치 화면을 열지 못했습니다. 아래 설치 방법을 확인해 주세요.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <InstallContext.Provider
      value={{ available, busy, standalone, installed, message, install }}
    >
      {children}
    </InstallContext.Provider>
  );
}

export function AppInstallPanel() {
  const state = useContext(InstallContext);
  if (!state) return null;
  return (
    <Panel
      className="live-span"
      title="모바일 앱"
      action={<Smartphone size={21} aria-hidden="true" />}
    >
      <div className="live-install-content">
        <div>
          <p>
            <strong>
              {state.standalone
                ? "앱으로 사용 중"
                : state.installed
                  ? "설치 완료"
                  : "홈 화면에서 바로 열기"}
            </strong>
          </p>
          <p>기존 계정으로 같은 사육장과 기록을 확인합니다.</p>
          <p className="live-note">데이터 조회에는 인터넷 연결이 필요합니다.</p>
        </div>
        <div>
          {!state.standalone && !state.installed && (
            <>
              {state.available && (
                <button onClick={() => void state.install()} disabled={state.busy}>
                  <Download size={17} aria-hidden="true" />앱 설치
                </button>
              )}
              <details open={!state.available}>
                <summary>설치 방법</summary>
                <dl className="live-description">
                  <dt>iPhone · Safari</dt><dd>공유 → 홈 화면에 추가</dd>
                  <dt>Android · Chrome</dt><dd>메뉴 → 앱 설치 또는 홈 화면에 추가</dd>
                </dl>
              </details>
            </>
          )}
          {state.message && <p role="status" className="live-note">{state.message}</p>}
        </div>
      </div>
    </Panel>
  );
}
