import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingState, PageHeader } from "@/components/states";
import { t } from "@/i18n";

import { InsightsView } from "./insights-view";

export const metadata: Metadata = { title: t.pages.insights.title };

export default function Page() {
  return (
    <>
      <PageHeader title={t.pages.insights.title} description={t.pages.insights.description} />
      <Suspense fallback={<LoadingState />}>
        <InsightsView />
      </Suspense>
    </>
  );
}
