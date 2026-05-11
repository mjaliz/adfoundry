import { BrowserRouter, Navigate, Outlet, Route, Routes } from "react-router-dom";

import { AppShell } from "@/components/app-shell";
import { HomePage } from "@/pages/home-page";
import { RunPage } from "@/pages/run-page";
import { SetupPage } from "@/pages/setup-page";
import { getCredentials } from "@/lib/credentials";

function RequireCredentials() {
  if (!getCredentials()) {
    return <Navigate to="/setup" replace />;
  }
  return <Outlet />;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route path="setup" element={<SetupPage />} />
          <Route element={<RequireCredentials />}>
            <Route index element={<HomePage />} />
            <Route path="runs/:id" element={<RunPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
