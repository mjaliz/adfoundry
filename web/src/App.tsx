import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "@/components/app-shell";
import { HomePage } from "@/pages/home-page";
import { RunPage } from "@/pages/run-page";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<HomePage />} />
          <Route path="runs/:id" element={<RunPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
