import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { LandingPage } from "./pages/LandingPage";
import { BenchmarkPage } from "./pages/BenchmarkPage";
import { Harness2Page } from "./pages/Harness2Page";
import { Harness2HistoryPage } from "./pages/Harness2HistoryPage";
import { TrackBHistoryPage } from "./pages/TrackBHistoryPage";
import { TrackBPage } from "./pages/TrackBPage";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/benchmark" element={<BenchmarkPage />} />
        <Route path="/trackb" element={<TrackBPage />} />
        <Route path="/trackb/harness2" element={<Harness2Page />} />
        <Route path="/trackb/harness2/history" element={<Harness2HistoryPage />} />
        <Route path="/trackb/history" element={<TrackBHistoryPage />} />
        <Route path="/trackb/h1" element={<Navigate to="/trackb" replace />} />
        <Route path="/trackb/h2" element={<Navigate to="/trackb" replace />} />
        <Route path="/trackb/h3" element={<Navigate to="/trackb" replace />} />
        <Route path="/trackb/h4" element={<Navigate to="/trackb" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
);
