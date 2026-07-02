import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { LandingPage } from "./pages/LandingPage";
import { BenchmarkPage } from "./pages/BenchmarkPage";
import { TrackBPage } from "./pages/TrackBPage";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/benchmark" element={<BenchmarkPage />} />
        <Route path="/trackb" element={<TrackBPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
);
