import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingState, PageHeader } from "@/components/states";
import { t } from "@/i18n";

import { OptimizerView } from "./optimizer-view";

export const metadata: Metadata = { title: t.pages.optimizer.title };

export default function Page() {
  return (
    <>
      <PageHeader title={t.pages.optimizer.title} description={t.pages.optimizer.description} />
      <Suspense fallback={<LoadingState />}>
        <OptimizerView />
      </Suspense>
    </>
  );
}
