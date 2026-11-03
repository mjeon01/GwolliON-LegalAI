import React from "react";
import ReactDOM from "react-dom/client";
import "@fontsource/space-grotesk/latin-700.css";
import "pretendard/dist/web/variable/pretendardvariable.css";
import "./styles/global.css";
import App from "./App.jsx";
import "./styles/workspace.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
