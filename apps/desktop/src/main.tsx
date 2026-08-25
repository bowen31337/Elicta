import React from "react";
import ReactDOM from "react-dom/client";
import { AppRouter } from "./router";
import { listenForServiceReady } from "./services/serviceReadySignal";
import "./styles.css";

// Before the first render, so a screen refused while the service was still
// starting is re-asked the moment the shell says it is answering.
void listenForServiceReady();

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <AppRouter />
  </React.StrictMode>,
);
