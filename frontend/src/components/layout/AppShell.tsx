"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BarChart3, Waves, GitBranch, Star, Clock,
  Layers, Brain, FileText, Settings, Menu, X,
  Activity, Telescope, Zap
} from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/",           label: "Research",     icon: BarChart3,  pro: false },
  { href: "/cycles",     label: "Cycles",       icon: Waves,      pro: false },
  { href: "/patterns",   label: "Patterns",     icon: GitBranch,  pro: false },
  { href: "/analogs",    label: "Analogs",      icon: Clock,      pro: true  },
  { href: "/planetary",  label: "Planetary",    icon: Telescope,  pro: true  },
  { href: "/features",   label: "Features",     icon: Layers,     pro: true  },
  { href: "/models",     label: "AI Models",    icon: Brain,      pro: true  },
  { href: "/reports",    label: "Reports",      icon: FileText,   pro: false },
  { href: "/settings",   label: "Settings",     icon: Settings,   pro: false },
];

interface AppShellProps {
  children: React.ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  const pathname = usePathname();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      {/* ── Sidebar ────────────────────────────────────────────────── */}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-50 w-56 flex flex-col bg-card border-r border-border transition-transform duration-200",
          sidebarOpen ? "translate-x-0" : "-translate-x-full",
          "lg:relative lg:translate-x-0"
        )}
      >
        {/* Logo */}
        <div className="flex items-center gap-2 px-4 py-5 border-b border-border">
          <div className="w-7 h-7 rounded bg-primary/20 flex items-center justify-center">
            <Activity className="w-4 h-4 text-primary" />
          </div>
          <div>
            <div className="text-xs font-bold tracking-wider text-gradient">HCD AI</div>
            <div className="text-[10px] text-muted-foreground">Cycle Discovery</div>
          </div>
          <button
            className="ml-auto lg:hidden text-muted-foreground"
            onClick={() => setSidebarOpen(false)}
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Nav */}
        <nav className="flex-1 py-4 overflow-y-auto">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex items-center gap-3 px-4 py-2.5 text-sm transition-colors relative",
                  active
                    ? "text-primary bg-primary/10"
                    : "text-muted-foreground hover:text-foreground hover:bg-secondary"
                )}
              >
                {active && (
                  <span className="absolute left-0 inset-y-0 w-0.5 bg-primary rounded-r" />
                )}
                <Icon className="w-4 h-4 flex-shrink-0" />
                <span>{item.label}</span>
                {item.pro && (
                  <span className="ml-auto text-[9px] font-bold text-primary/70 border border-primary/30 rounded px-1">
                    PRO
                  </span>
                )}
              </Link>
            );
          })}
        </nav>

        {/* Plan badge */}
        <div className="px-4 py-4 border-t border-border">
          <div className="glow-card text-xs">
            <div className="flex items-center gap-2 mb-1">
              <Zap className="w-3 h-3 text-primary" />
              <span className="text-primary font-medium">Free Plan</span>
            </div>
            <p className="text-muted-foreground text-[10px]">
              Upgrade to Pro for full cycle analysis, analogs & AI models.
            </p>
            <Link
              href="/upgrade"
              className="mt-2 block text-center text-[10px] font-medium text-background bg-primary rounded px-2 py-1 hover:bg-primary/90 transition-colors"
            >
              Upgrade to Pro
            </Link>
          </div>
        </div>
      </aside>

      {/* ── Main content ──────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Top bar */}
        <header className="flex items-center gap-4 px-4 py-3 border-b border-border bg-card/50 backdrop-blur">
          <button
            className="lg:hidden text-muted-foreground"
            onClick={() => setSidebarOpen(true)}
          >
            <Menu className="w-5 h-5" />
          </button>
          <h1 className="text-sm font-semibold text-foreground">
            Hidden Cycle Discovery AI
          </h1>
          <div className="ml-auto flex items-center gap-2">
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <div className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
              System online
            </div>
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-y-auto">
          {children}
        </main>
      </div>

      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-40 bg-background/80 backdrop-blur-sm lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}
    </div>
  );
}
