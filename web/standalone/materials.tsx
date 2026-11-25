import { createRoot } from "react-dom/client";
import Presentation from "./presentation";
import "../app/globals.css";
import "../app/forest-scene.css";
import "./live-workspace.css";
import "./materials.css";

createRoot(document.getElementById("root")!).render(
  <div className="forest-scene live-workspace public-materials">
    <main className="live-main" id="live-content">
      <div className="live-body">
        <Presentation onReturn={() => window.location.assign("/")} />
      </div>
    </main>
  </div>,
);
