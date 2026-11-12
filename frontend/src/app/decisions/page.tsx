import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingState, PageHeader } from "@/components/states";
import { t } from "@/i18n";

import { DecisionsView } from "./decisions-view";

export const metadata: Metadata = { title: t.pages.decisions.title };

export default function Page() {
  return (
    <>
      <PageHeader title={t.pages.decisions.title} description={t.pages.decisions.description} />
      <Suspense fallback={<LoadingState />}>
        <DecisionsView />
      </Suspense>
    </>
  );
}
