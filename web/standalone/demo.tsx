import { createRoot } from "react-dom/client";
import { HabitatApp } from "../components/habitat/habitat-app";
import "../app/globals.css";
import "../app/forest-scene.css";
import "../app/dashboard-layout.css";
import "../app/account-management.css";

createRoot(document.getElementById("root")!).render(<HabitatApp publicDemo />);
