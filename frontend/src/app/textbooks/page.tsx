import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingState, PageHeader } from "@/components/states";
import { t } from "@/i18n";

import { TextbooksView } from "./textbooks-view";

export const metadata: Metadata = { title: t.pages.textbooks.title };

export default function Page() {
  return (
    <>
      <PageHeader title={t.pages.textbooks.title} description={t.pages.textbooks.description} />
      <Suspense fallback={<LoadingState />}>
        <TextbooksView />
      </Suspense>
    </>
  );
}
