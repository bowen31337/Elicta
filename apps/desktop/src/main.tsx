import React from "react";
import ReactDOM from "react-dom/client";
import { AppRouter } from "./router";
import { listenForServiceReady } from "./services/serviceReadySignal";
import { refuseStrayDrops } from "./services/strayDrop";
import "./styles.css";

// Before the first render, so a screen refused while the service was still
// starting is re-asked the moment the shell says it is answering.
void listenForServiceReady();

// For the lifetime of the window, and never removed: a document dropped
// anywhere that does not accept one would otherwise navigate the webview to
// it, and in the packaged app there is no address bar to come back from.
refuseStrayDrops();

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <AppRouter />
  </React.StrictMode>,
);
