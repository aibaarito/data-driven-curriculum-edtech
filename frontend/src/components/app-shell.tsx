"use client";

import {
  Table2,
  BarChart3,
  BookOpenCheck,
  FileText,
  GitBranch,
  GraduationCap,
  Layers,
  LayoutDashboard,
  Menu,
  Scale,
  Settings,
  Sparkles,
  Target,
  Upload,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { Suspense, useState, type ReactNode } from "react";

import { useMeta } from "@/components/meta-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { t } from "@/i18n";
import { parseFilters, toQuery } from "@/lib/filters";
import { cn } from "@/lib/utils";

export const NAV = [
  { href: "/", label: t.nav.dashboard, icon: LayoutDashboard },
  { href: "/decisions", label: t.nav.decisions, icon: Target },
  { href: "/import", label: t.nav.import, icon: Upload },
  { href: "/datasets", label: t.nav.datasets, icon: Table2 },
  { href: "/topics", label: t.nav.topics, icon: BarChart3 },
  { href: "/curriculum", label: t.nav.curriculum, icon: GitBranch },
  { href: "/textbooks", label: t.nav.textbooks, icon: Scale },
  { href: "/optimizer", label: t.nav.optimizer, icon: BookOpenCheck },
  { href: "/scenarios", label: t.nav.scenarios, icon: Layers },
  { href: "/insights", label: t.nav.insights, icon: Sparkles },
  { href: "/reports", label: t.nav.reports, icon: FileText },
  { href: "/settings", label: t.nav.settings, icon: Settings },
] as const;

/** Links carry the current analysis filters; each screen applies what it supports and explains the rest. */
function ScopedNavLinks({ onNavigate }: { onNavigate?: () => void }) {
  const params = useSearchParams();
  return <NavLinks onNavigate={onNavigate} query={toQuery(parseFilters(params))} />;
}

function Nav({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <Suspense fallback={<NavLinks onNavigate={onNavigate} />}>
      <ScopedNavLinks onNavigate={onNavigate} />
    </Suspense>
  );
}

function NavLinks({ onNavigate, query = "" }: { onNavigate?: () => void; query?: string }) {
  const pathname = usePathname();
  return (
    <nav className="flex flex-col gap-0.5" aria-label="Основная навигация">
      {NAV.map(({ href, label, icon: Icon }) => {
        const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
        return (
          <Link
            key={href}
            href={`${href}${query}`}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
              active ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            <Icon className="size-4 shrink-0" aria-hidden />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}

function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <Link href="/" className="flex items-center gap-2.5 rounded-lg px-1 outline-none focus-visible:ring-2 focus-visible:ring-ring">
      <span className="grid size-8 place-items-center rounded-lg bg-primary text-primary-foreground shadow-sm">
        <GraduationCap className="size-4.5" aria-hidden />
      </span>
      <span className={cn("leading-tight", compact && "max-[420px]:hidden")}>
        <span className="block text-sm font-semibold tracking-tight">{t.app.name}</span>
        {!compact && <span className="block text-xs text-muted-foreground">{t.app.tagline}</span>}
      </span>
    </Link>
  );
}

function SyntheticBadge() {
  const { data } = useMeta();
  if (!data?.synthetic) return null;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Badge variant="outline" className="border-warning/50 bg-warning/10 text-amber-800" data-testid="synthetic-badge">
          {t.app.synthetic}
        </Badge>
      </TooltipTrigger>
      <TooltipContent className="max-w-64">{t.app.syntheticHint}</TooltipContent>
    </Tooltip>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="min-h-dvh">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 flex-col border-r bg-sidebar px-4 py-5 lg:flex">
        <Brand />
        <div className="mt-8 flex-1">
          <Nav />
        </div>
        <div className="space-y-2 border-t pt-4 text-xs text-muted-foreground">
          <SyntheticBadge />
          <p>Расчёты выполняются на сервере детерминированно; ИИ только объясняет результаты.</p>
        </div>
      </aside>

      <header className="sticky top-0 z-20 flex h-14 items-center justify-between gap-3 border-b bg-background/90 px-4 backdrop-blur lg:hidden">
        <Brand compact />
        <div className="flex items-center gap-2">
          <SyntheticBadge />
          <Sheet open={open} onOpenChange={setOpen}>
            <SheetTrigger asChild>
              <Button variant="outline" size="icon" aria-label="Открыть меню">
                <Menu className="size-4" />
              </Button>
            </SheetTrigger>
            <SheetContent side="left" className="w-72 p-4">
              <SheetHeader className="p-0 pb-4">
                <SheetTitle>
                  <Brand />
                </SheetTitle>
              </SheetHeader>
              <Nav onNavigate={() => setOpen(false)} />
            </SheetContent>
          </Sheet>
        </div>
      </header>

      <main className="lg:pl-64">
        <div className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8 lg:py-8">{children}</div>
      </main>
    </div>
  );
}
