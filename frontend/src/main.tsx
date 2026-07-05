import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { LandingPage } from "./pages/LandingPage";
import { BenchmarkPage } from "./pages/BenchmarkPage";
import { TrackBHistoryPage } from "./pages/TrackBHistoryPage";
import { TrackBH1Page } from "./pages/TrackBH1Page";
import { TrackBH2Page } from "./pages/TrackBH2Page";
import { TrackBH3Page } from "./pages/TrackBH3Page";
import { TrackBH4Page } from "./pages/TrackBH4Page";
import { TrackBChatPage } from "./pages/TrackBChatPage";
import { TrackBPage } from "./pages/TrackBPage";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/benchmark" element={<BenchmarkPage />} />
        <Route path="/trackb" element={<TrackBPage />} />
        <Route path="/trackb/chat" element={<TrackBChatPage />} />
        <Route path="/trackb/history" element={<TrackBHistoryPage />} />
        <Route path="/trackb/h1" element={<TrackBH1Page />} />
        <Route path="/trackb/h2" element={<TrackBH2Page />} />
        <Route path="/trackb/h3" element={<TrackBH3Page />} />
        <Route path="/trackb/h4" element={<TrackBH4Page />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
);
