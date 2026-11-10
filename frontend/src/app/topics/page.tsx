import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingState, PageHeader } from "@/components/states";
import { t } from "@/i18n";

import { TopicsView } from "./topics-view";

export const metadata: Metadata = { title: t.pages.topics.title };

export default function Page() {
  return (
    <>
      <PageHeader title={t.pages.topics.title} description={t.pages.topics.description} />
      <Suspense fallback={<LoadingState />}>
        <TopicsView />
      </Suspense>
    </>
  );
}
