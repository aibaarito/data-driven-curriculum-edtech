import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingState, PageHeader } from "@/components/states";
import { t } from "@/i18n";

import { ReportsView } from "./reports-view";

export const metadata: Metadata = { title: t.pages.reports.title };

export default function Page() {
  return (
    <>
      <PageHeader title={t.pages.reports.title} description={t.pages.reports.description} />
      <Suspense fallback={<LoadingState />}>
        <ReportsView />
      </Suspense>
    </>
  );
}
