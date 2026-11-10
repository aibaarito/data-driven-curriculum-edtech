import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";

import { AppShell } from "@/components/app-shell";
import { MetaProvider } from "@/components/meta-provider";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { LOCALE, t } from "@/i18n";

import "./globals.css";

const inter = Inter({ variable: "--font-sans", subsets: ["latin", "cyrillic"], display: "swap" });

export const metadata: Metadata = {
  title: { default: t.app.name, template: `%s · ${t.app.name}` },
  description: "Аналитика результатов оцениваний и прозрачные рекомендации по учебной программе.",
};

export const viewport: Viewport = { themeColor: "#4f46e5" };

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang={LOCALE} className={`${inter.variable} h-full antialiased`}>
      <body className="min-h-full bg-background font-sans text-foreground">
        <TooltipProvider delayDuration={200}>
          <MetaProvider>
            <AppShell>{children}</AppShell>
          </MetaProvider>
        </TooltipProvider>
        <Toaster position="top-right" richColors closeButton />
      </body>
    </html>
  );
}
