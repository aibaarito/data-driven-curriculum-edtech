import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingState, PageHeader } from "@/components/states";
import { t } from "@/i18n";

import { CurriculumView } from "./curriculum-view";

export const metadata: Metadata = { title: t.pages.curriculum.title };

export default function Page() {
  return (
    <>
      <PageHeader title={t.pages.curriculum.title} description={t.pages.curriculum.description} />
      <Suspense fallback={<LoadingState />}>
        <CurriculumView />
      </Suspense>
    </>
  );
}
