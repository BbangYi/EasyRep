import { createRoot } from "react-dom/client";
import { AuthenticatedApp } from "./authenticated-app";
import "../app/globals.css";
import "../app/forest-scene.css";
import "../app/dashboard-layout.css";
import "../app/account-management.css";

createRoot(document.getElementById("root")!).render(<AuthenticatedApp />);
