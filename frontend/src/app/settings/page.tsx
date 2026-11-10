import type { Metadata } from "next";
import { Suspense } from "react";

import { LoadingState, PageHeader } from "@/components/states";
import { t } from "@/i18n";

import { SettingsView } from "./settings-view";

export const metadata: Metadata = { title: t.pages.settings.title };

export default function Page() {
  return (
    <>
      <PageHeader title={t.pages.settings.title} description={t.pages.settings.description} />
      <Suspense fallback={<LoadingState />}>
        <SettingsView />
      </Suspense>
    </>
  );
}
