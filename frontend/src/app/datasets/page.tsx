import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingState, PageHeader } from "@/components/states";
import { t } from "@/i18n";

import { DatasetsView } from "./datasets-view";

export const metadata: Metadata = { title: t.pages.datasets.title };

export default function Page() {
  return (
    <>
      <PageHeader title={t.pages.datasets.title} description={t.pages.datasets.description} />
      <Suspense fallback={<LoadingState />}>
        <DatasetsView />
      </Suspense>
    </>
  );
}
