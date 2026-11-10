import type { Metadata } from "next";

import { PageHeader } from "@/components/states";
import { t } from "@/i18n";

import { ImportView } from "./import-view";

export const metadata: Metadata = { title: t.pages.import.title };

export default function Page() {
  return (
    <>
      <PageHeader title={t.pages.import.title} description={t.pages.import.description} />
      <ImportView />
    </>
  );
}
