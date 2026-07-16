import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { FernProvider } from "./store";
import App from "./App";
import "./styles/variables.css";
import "./styles/theme.css";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <BrowserRouter basename="/ui">
      <FernProvider>
        <App />
      </FernProvider>
    </BrowserRouter>
  </React.StrictMode>
);
