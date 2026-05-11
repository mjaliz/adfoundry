import { Link, Outlet } from "react-router-dom";
import { Sparkles } from "lucide-react";

import { Toaster } from "@/components/ui/sonner";

export function AppShell() {
  return (
    <div className="min-h-full bg-background text-foreground">
      <header className="sticky top-0 z-30 border-b bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="mx-auto flex h-14 max-w-screen-2xl items-center gap-3 px-6">
          <Link to="/" className="flex items-center gap-2 font-semibold">
            <span className="grid h-8 w-8 place-items-center rounded-md bg-primary text-primary-foreground">
              <Sparkles className="h-4 w-4" />
            </span>
            <span className="text-base tracking-tight">AdFoundry</span>
            <span className="hidden text-xs font-normal text-muted-foreground sm:inline">
              Live agentic campaign builder
            </span>
          </Link>
        </div>
      </header>
      <main className="mx-auto max-w-screen-2xl px-6 py-6">
        <Outlet />
      </main>
      <Toaster richColors closeButton position="top-right" />
    </div>
  );
}
