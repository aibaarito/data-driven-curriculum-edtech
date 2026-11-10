import { Suspense } from "react";

import { LoadingState, PageHeader } from "@/components/states";
import { t } from "@/i18n";

import { DashboardView } from "./dashboard-view";

export default function Page() {
  return (
    <>
      <PageHeader title={t.pages.dashboard.title} description={t.pages.dashboard.description} />
      <Suspense fallback={<LoadingState />}>
        <DashboardView />
      </Suspense>
    </>
  );
}
