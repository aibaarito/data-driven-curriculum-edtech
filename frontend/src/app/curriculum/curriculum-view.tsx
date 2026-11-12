"use client";

import { Search } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { EvidenceBadge, TopicPassportButton } from "@/components/evidence-passport";
import { RequireData } from "@/components/page-frame";
import { PlanScope } from "@/components/plan-scope";
import { ErrorState, LoadingState } from "@/components/states";
import { StatusBadge } from "@/components/ui-bits";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useApi } from "@/hooks/use-api";
import type { CurriculumGraph, GraphNode } from "@/lib/decision-types";
import { num, pct } from "@/lib/format";
import { DIRECTION_LABEL } from "@/lib/gain";
import { cn } from "@/lib/utils";

const NODE_W = 184;
const NODE_H = 60;
const COL_GAP = 64;
const ROW_GAP = 18;
const PAD = 12;

const FILL: Record<string, string> = {
  difficult: "fill-[color-mix(in_oklab,var(--danger)_14%,var(--card))] stroke-danger",
  watch: "fill-[color-mix(in_oklab,var(--warning)_18%,var(--card))] stroke-warning",
  ok: "fill-card stroke-[color-mix(in_oklab,var(--success)_70%,var(--border))]",
  insufficient_data: "fill-muted stroke-border",
  no_outcome_data: "fill-muted stroke-border",
};

export function CurriculumView() {
  return (
    <RequireData>
      <PlanScope screen="/curriculum" idPrefix="cm">
        {({ subjectId, grade }) => <MapLoader key={`${subjectId}-${grade}`} subjectId={subjectId} grade={grade} />}
      </PlanScope>
    </RequireData>
  );
}

function MapLoader({ subjectId, grade }: { subjectId: number; grade: number }) {
  const g = useApi<CurriculumGraph>(`/api/curriculum/graph?subject_id=${subjectId}&grade=${grade}`);
  if (g.error) return <ErrorState error={g.error} onRetry={g.reload} />;
  if (g.loading || !g.data) return <LoadingState rows={2} />;
  if (g.data.nodes.length === 0) return <p className="text-sm text-muted-foreground" data-testid="graph-empty">Для выбранного среза нет тем.</p>;
  return <CurriculumMap graph={g.data} subjectId={subjectId} grade={grade} />;
}

function layout(nodes: GraphNode[]) {
  const cols = new Map<number, GraphNode[]>();
  for (const n of nodes) cols.set(n.depth, [...(cols.get(n.depth) ?? []), n]);
  const pos = new Map<number, { x: number; y: number }>();
  let maxRows = 0;
  for (const [depth, list] of cols) {
    list.sort((a, b) => a.grade - b.grade || a.order - b.order || a.code.localeCompare(b.code));
    maxRows = Math.max(maxRows, list.length);
    list.forEach((n, i) => pos.set(n.topic_id, { x: PAD + depth * (NODE_W + COL_GAP), y: PAD + i * (NODE_H + ROW_GAP) }));
  }
  const width = PAD * 2 + Math.max(1, cols.size) * (NODE_W + COL_GAP) - COL_GAP;
  const height = PAD * 2 + Math.max(1, maxRows) * (NODE_H + ROW_GAP) - ROW_GAP;
  return { pos, width, height };
}

function CurriculumMap({ graph, subjectId, grade }: { graph: CurriculumGraph; subjectId: number; grade: number }) {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const [query, setQuery] = useState("");
  const byId = useMemo(() => new Map(graph.nodes.map((n) => [n.topic_id, n])), [graph]);
  const fromUrl = Number(params.get("topic"));
  const selected = byId.has(fromUrl) ? fromUrl : null;
  const [chain, setChain] = useState<number[] | null>(null);
  const { pos, width, height } = useMemo(() => layout(graph.nodes), [graph]);

  const select = (id: number | null) => {
    setChain(null);
    const p = new URLSearchParams(params.toString());
    if (id === null) p.delete("topic");
    else p.set("topic", String(id));
    const q = p.toString();
    router.replace(`${pathname}${q ? `?${q}` : ""}`, { scroll: false });
  };

  const highlighted = useMemo(() => {
    if (chain) return new Set(chain);
    if (selected === null) return null;
    const n = byId.get(selected);
    return n ? new Set([selected, ...n.ancestors, ...n.descendants]) : null;
  }, [chain, selected, byId]);
  const q = query.trim().toLowerCase();
  const matches = (n: GraphNode) => !q || n.name.toLowerCase().includes(q) || n.code.toLowerCase().includes(q);
  const sel = selected !== null ? byId.get(selected) ?? null : null;
  const passportQuery = `?subject_id=${subjectId}&grade=${grade}`;

  return (
    <div className="space-y-6">
      {!graph.valid && (
        <Alert variant="destructive" data-testid="graph-invalid">
          <AlertTitle>Граф пререквизитов некорректен</AlertTitle>
          <AlertDescription>
            <ul className="list-disc pl-5">{graph.issues.map((i) => <li key={i.message}>{i.message}</li>)}</ul>
            Диагностика зависимостей отключена до исправления.
          </AlertDescription>
        </Alert>
      )}
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <Card className="min-w-0">
          <CardHeader>
            <CardTitle>Граф пререквизитов</CardTitle>
            <CardDescription>
              Слева направо — порядок изучения (стрелка: «изучается раньше»). Цвет — статус освоения. Выберите тему,
              чтобы увидеть её цепочку. Связи показывают структуру программы, а не доказанную причину результатов.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex flex-wrap items-end gap-3">
              <div className="flex min-w-48 flex-1 flex-col gap-1.5 sm:max-w-xs">
                <Label htmlFor="cm-search" className="text-xs text-muted-foreground">Поиск темы</Label>
                <div className="relative">
                  <Search className="pointer-events-none absolute top-2.5 left-2.5 size-4 text-muted-foreground" aria-hidden />
                  <Input id="cm-search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Название или код" className="pl-8" />
                </div>
              </div>
              {(selected !== null || chain) && <Button variant="ghost" size="sm" onClick={() => select(null)}>Снять выделение</Button>}
            </div>
            <Legend />
            <div className="overflow-x-auto rounded-lg border bg-background" data-testid="graph-canvas">
              {/* Scales down to fit the card (to 75% of natural size), then scrolls horizontally inside the card. */}
              <svg width="100%" viewBox={`0 0 ${width} ${height}`} role="group" aria-label="Граф пререквизитов программы"
                className="block h-auto" style={{ minWidth: Math.round(width * 0.75), maxWidth: width }}>
                <defs>
                  <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                    <path d="M0,0 L10,5 L0,10 z" className="fill-muted-foreground" />
                  </marker>
                </defs>
                {graph.edges.filter((e) => e.review_status !== "rejected").map((e) => {
                  const a = pos.get(e.prerequisite_id);
                  const b = pos.get(e.topic_id);
                  if (!a || !b) return null;
                  const on = !highlighted || (highlighted.has(e.prerequisite_id) && highlighted.has(e.topic_id));
                  const x1 = a.x + NODE_W, y1 = a.y + NODE_H / 2, x2 = b.x - 2, y2 = b.y + NODE_H / 2;
                  const mx = (x1 + x2) / 2;
                  return (
                    <path key={`${e.prerequisite_id}-${e.topic_id}`} d={`M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`}
                      markerEnd="url(#arrow)" fill="none"
                      className={cn("stroke-muted-foreground transition-opacity", e.weak_link && "stroke-danger",
                        e.review_status === "pending" && "[stroke-dasharray:5_4]", on ? "opacity-90" : "opacity-15")}
                      strokeWidth={e.weak_link ? 2 : 1.25} />
                  );
                })}
                {graph.nodes.map((n) => {
                  const p = pos.get(n.topic_id)!;
                  const dim = (highlighted && !highlighted.has(n.topic_id)) || !matches(n);
                  const isSel = n.topic_id === selected;
                  return (
                    <g key={n.topic_id} transform={`translate(${p.x},${p.y})`} role="button" tabIndex={0}
                      aria-pressed={isSel} aria-label={`${n.name}: освоение ${pct(n.mastery)}, ${n.evidence.label}${n.foundational_gap ? ", слабый пререквизит" : ""}`}
                      data-testid={`node-${n.code}`}
                      onClick={() => select(isSel ? null : n.topic_id)}
                      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(isSel ? null : n.topic_id); } }}
                      className={cn("cursor-pointer outline-none transition-opacity focus-visible:[&>rect]:stroke-ring focus-visible:[&>rect]:stroke-[3]",
                        dim ? "opacity-30" : "opacity-100")}>
                      <rect width={NODE_W} height={NODE_H} rx={10} strokeWidth={isSel ? 3 : 1.5}
                        className={cn(FILL[n.status] ?? FILL.no_outcome_data, !n.in_scope && "[stroke-dasharray:4_3]")} />
                      <text x={10} y={22} className="fill-foreground text-[12px] font-medium">
                        {n.name.length > 24 ? `${n.name.slice(0, 23)}…` : n.name}
                      </text>
                      <text x={10} y={42} className="fill-muted-foreground text-[11px]">
                        {pct(n.mastery)} · приоритет {num(n.priority.score)}{!n.in_scope ? ` · ${n.grade} кл.` : ""}
                      </text>
                      {n.foundational_gap && <circle cx={NODE_W - 12} cy={12} r={5} className="fill-danger" aria-hidden />}
                    </g>
                  );
                })}
              </svg>
            </div>
          </CardContent>
        </Card>
        <div className="space-y-4">
          <SelectedPanel node={sel} byId={byId} passportQuery={passportQuery} />
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Критические цепочки</CardTitle>
              <CardDescription>Пути программы, где подряд встречаются ≥ 2 слабые темы.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {graph.chains.length === 0 && <p className="text-sm text-muted-foreground">Цепочек со слабыми темами нет.</p>}
              {graph.chains.map((c) => (
                <button key={c.path.join("-")} type="button" onClick={() => setChain(c.path)}
                  className={cn("w-full rounded-lg border p-2 text-left text-sm hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring outline-none",
                    chain?.join() === c.path.join() && "border-primary bg-accent")} data-testid="chain">
                  {c.names.map((name, i) => (
                    <span key={name}>
                      <span className={cn(c.weak.includes(c.path[i]) && "font-semibold text-danger")}>{name}</span>
                      {i < c.names.length - 1 && <span className="text-muted-foreground"> → </span>}
                    </span>
                  ))}
                </button>
              ))}
            </CardContent>
          </Card>
        </div>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Темы и приоритеты (таблица)</CardTitle>
          <CardDescription>
            Приоритет = {graph.heuristic.formula}. {graph.heuristic.note}
          </CardDescription>
        </CardHeader>
        <CardContent className="overflow-x-auto">
          <Table data-testid="graph-table">
            <TableHeader>
              <TableRow>
                <TableHead>Тема</TableHead>
                <TableHead className="text-right">Освоение</TableHead>
                <TableHead>Статус</TableHead>
                <TableHead>Доказательства</TableHead>
                <TableHead className="text-right">Приоритет</TableHead>
                <TableHead>Пререквизиты</TableHead>
                <TableHead className="text-right">Зависимых</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {graph.nodes.filter(matches).map((n) => (
                <TableRow key={n.topic_id} className={cn(n.topic_id === selected && "bg-accent/60")}>
                  <TableCell className="font-medium">
                    <button type="button" className="text-left underline-offset-2 hover:underline" onClick={() => select(n.topic_id)}>{n.name}</button>
                    {n.foundational_gap && <Badge variant="outline" className="ml-2 border-danger/30 text-danger">слабый пререквизит</Badge>}
                    {!n.in_scope && <span className="ml-2 text-xs text-muted-foreground">({n.grade} кл., вне среза)</span>}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{pct(n.mastery)}</TableCell>
                  <TableCell><StatusBadge status={n.status} /></TableCell>
                  <TableCell><EvidenceBadge category={n.evidence.category} /></TableCell>
                  <TableCell className="text-right tabular-nums">{num(n.priority.score)}</TableCell>
                  <TableCell className="text-sm">{n.prerequisites.map((p) => byId.get(p)?.name).filter(Boolean).join(", ") || "—"}</TableCell>
                  <TableCell className="text-right tabular-nums">{n.downstream_count}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

function Legend() {
  const items = [
    ["bg-[color-mix(in_oklab,var(--danger)_14%,var(--card))] border-danger", "Трудная"],
    ["bg-[color-mix(in_oklab,var(--warning)_18%,var(--card))] border-warning", "Внимание"],
    ["bg-card border-[color-mix(in_oklab,var(--success)_70%,var(--border))]", "Норма"],
    ["bg-muted border-border", "Нет/мало данных"],
  ];
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground" aria-label="Легенда">
      {items.map(([cls, label]) => (
        <li key={label} className="flex items-center gap-1.5"><span className={cn("inline-block size-3 rounded border", cls)} aria-hidden />{label}</li>
      ))}
      <li className="flex items-center gap-1.5"><span className="inline-block size-2.5 rounded-full bg-danger" aria-hidden />слабый пререквизит слабых тем</li>
      <li className="flex items-center gap-1.5"><span className="inline-block h-0 w-5 border-t-2 border-danger" aria-hidden />связь двух слабых тем</li>
      <li className="flex items-center gap-1.5"><span className="inline-block h-0 w-5 border-t border-dashed border-muted-foreground" aria-hidden />связь на проверке</li>
    </ul>
  );
}

function SelectedPanel({ node, byId, passportQuery }: { node: GraphNode | null; byId: Map<number, GraphNode>; passportQuery: string }) {
  if (!node) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Тема не выбрана</CardTitle>
          <CardDescription>Выберите тему на графе или в таблице, чтобы увидеть, почему она в приоритете.</CardDescription>
        </CardHeader>
      </Card>
    );
  }
  const names = (ids: number[]) => ids.map((i) => byId.get(i)?.name).filter(Boolean).join(", ") || "—";
  return (
    <Card data-testid="selected-topic">
      <CardHeader>
        <CardTitle className="text-base">{node.name}</CardTitle>
        <CardDescription className="flex flex-wrap gap-1.5 pt-1">
          <StatusBadge status={node.status} />
          <EvidenceBadge category={node.evidence.category} />
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <dl className="grid grid-cols-2 gap-2">
          <div><dt className="text-xs text-muted-foreground">Освоение</dt><dd className="font-medium tabular-nums">{pct(node.mastery)}</dd></div>
          <div><dt className="text-xs text-muted-foreground">Учеников</dt><dd className="font-medium tabular-nums">{node.student_count}</dd></div>
          <div><dt className="text-xs text-muted-foreground">Динамика</dt><dd>{node.gain_direction ? DIRECTION_LABEL[node.gain_direction as keyof typeof DIRECTION_LABEL] ?? node.gain_direction : "—"}</dd></div>
          <div><dt className="text-xs text-muted-foreground">Приоритет</dt><dd className="font-medium tabular-nums">{num(node.priority.score)} / 100</dd></div>
        </dl>
        <div>
          <p className="text-xs font-semibold text-muted-foreground uppercase">Почему такой приоритет</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-5" data-testid="why-priority">{node.why.map((w) => <li key={w}>{w}</li>)}</ul>
          <p className="mt-1 text-xs text-muted-foreground">
            Компоненты: разрыв {num(node.priority.components.gap, 2)}, программа {num(node.priority.components.curriculum, 2)},
            зависимость {num(node.priority.components.dependency, 2)}, доказательства {num(node.priority.components.evidence, 2)}.
          </p>
        </div>
        <p><span className="text-muted-foreground">Изучается после:</span> {names(node.ancestors)}</p>
        <p><span className="text-muted-foreground">Влияет на порядок изучения:</span> {names(node.descendants)}</p>
        <TopicPassportButton topicId={node.topic_id} topicName={node.name} query={passportQuery} />
      </CardContent>
    </Card>
  );
}
