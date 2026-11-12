"""Curriculum knowledge graph over the existing ``topic_prerequisites`` table.

Edge direction: prerequisite → dependent topic ("must be learned before"). Only approved edges are used by
diagnostics; pending/rejected edges are returned for review but never influence priorities or the optimizer.

All traversal is deterministic (tie-break by grade, curriculum order, code). The graph says which topics *precede*
others; it never asserts that a weak prerequisite *caused* weak results downstream.

Priority heuristic (documented in docs/ANALYTICS.md; NOT a trained predictor):
    gap        = clip((target − mastery) / target, 0, 1)      (0 when mastery unknown)
    curriculum = (priority − 1) / 2
    dependency = downstream_count / max_downstream_in_scope
    evidence   = {supported 1.0, exploratory 0.6, other 0}
    score      = 100 · evidence · gap · (0.6 + 0.2·curriculum + 0.2·dependency)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.services.evidence import assess_topic
from app.services.settings_store import AnalysisSettings

EVIDENCE_FACTOR = {"supported": 1.0, "exploratory": 0.6, "insufficient": 0.0, "incomparable": 0.0, "stale": 0.0}
W_BASE, W_CURRICULUM, W_DEPENDENCY = 0.6, 0.2, 0.2
WEAK_STATUSES = ("difficult", "watch")
MAX_CHAINS = 12


class GraphError(ValueError):
    """Invalid prerequisite structure. ``issues`` are machine-readable dicts with a code and message."""

    def __init__(self, message: str, issues: list[dict[str, Any]]):
        super().__init__(message)
        self.issues = issues


@dataclass(frozen=True)
class Node:
    id: int
    code: str
    name: str
    subject_id: int
    grade: int
    order: int
    priority: int = 2


@dataclass
class Edge:
    prerequisite_id: int
    topic_id: int
    id: int | None = None
    origin: str = "import"
    review_status: str = "approved"


@dataclass
class Graph:
    nodes: dict[int, Node]
    edges: list[Edge] = field(default_factory=list)

    def sort_key(self, tid: int) -> tuple:
        n = self.nodes[tid]
        return (n.grade, n.order, n.code)

    def approved(self) -> list[Edge]:
        return [e for e in self.edges if e.review_status == "approved"]


# --------------------------------------------------------------------------- validation


def find_cycle(node_ids: list[int], edges: list[tuple[int, int]]) -> list[int] | None:
    """Return one cycle as a node path [a, b, ..., a] if the directed graph (u → v) has one, else None.

    Iterative DFS with deterministic neighbour order, so the reported cycle is reproducible.
    """
    adj: dict[int, list[int]] = {n: [] for n in node_ids}
    for u, v in edges:
        adj.setdefault(u, []).append(v)
        adj.setdefault(v, [])
    for k in adj:
        adj[k].sort()
    color = {n: 0 for n in adj}  # 0 white, 1 on stack, 2 done
    for start in sorted(adj):
        if color[start]:
            continue
        stack: list[tuple[int, int]] = [(start, 0)]
        path: list[int] = [start]
        color[start] = 1
        while stack:
            node, idx = stack[-1]
            if idx < len(adj[node]):
                stack[-1] = (node, idx + 1)
                nxt = adj[node][idx]
                if color[nxt] == 1:
                    return path[path.index(nxt):] + [nxt]
                if color[nxt] == 0:
                    color[nxt] = 1
                    stack.append((nxt, 0))
                    path.append(nxt)
            else:
                color[node] = 2
                stack.pop()
                path.pop()
    return None


def validate_edges(nodes: dict[int, Node], edges: list[Edge]) -> list[dict[str, Any]]:
    """All structural problems of the approved+pending edge set (rejected edges are ignored)."""
    issues: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    live = [e for e in edges if e.review_status != "rejected"]
    for e in live:
        key = (e.prerequisite_id, e.topic_id)
        if e.prerequisite_id == e.topic_id:
            issues.append({"code": "SELF_PREREQUISITE", "message": "Тема не может быть пререквизитом самой себя.",
                           "topic_id": e.topic_id})
            continue
        if e.prerequisite_id not in nodes or e.topic_id not in nodes:
            issues.append({"code": "UNKNOWN_TOPIC", "message": "Связь ссылается на несуществующую тему.",
                           "topic_id": e.topic_id, "prerequisite_id": e.prerequisite_id})
            continue
        if key in seen:
            issues.append({"code": "DUPLICATE_EDGE", "message": "Связь задана повторно.", "topic_id": e.topic_id,
                           "prerequisite_id": e.prerequisite_id})
            continue
        seen.add(key)
        a, b = nodes[e.prerequisite_id], nodes[e.topic_id]
        if a.subject_id != b.subject_id:
            issues.append({"code": "CROSS_SUBJECT", "message": f"«{a.name}» и «{b.name}» относятся к разным предметам.",
                           "topic_id": b.id, "prerequisite_id": a.id})
        elif a.grade > b.grade:
            issues.append({"code": "GRADE_ORDER", "message": f"Пререквизит «{a.name}» изучается в более старшей "
                           f"параллели ({a.grade}), чем «{b.name}» ({b.grade}).", "topic_id": b.id,
                           "prerequisite_id": a.id})
    cyc = find_cycle(sorted(nodes), sorted(seen))
    if cyc:
        names = " → ".join(nodes[i].name for i in cyc)
        issues.append({"code": "CYCLE", "message": f"Циклическая зависимость: {names}.", "cycle": cyc})
    return issues


def topological_order(g: Graph, node_ids: list[int] | None = None) -> list[int]:
    """Kahn's algorithm over approved edges with a deterministic (grade, order, code) tie-break."""
    ids = set(node_ids if node_ids is not None else g.nodes)
    indeg = {i: 0 for i in ids}
    out: dict[int, list[int]] = {i: [] for i in ids}
    for e in g.approved():
        if e.prerequisite_id in ids and e.topic_id in ids:
            indeg[e.topic_id] += 1
            out[e.prerequisite_id].append(e.topic_id)
    ready = sorted([i for i, d in indeg.items() if d == 0], key=g.sort_key)
    order: list[int] = []
    while ready:
        n = ready.pop(0)
        order.append(n)
        for v in out[n]:
            indeg[v] -= 1
            if indeg[v] == 0:
                ready.append(v)
        ready.sort(key=g.sort_key)
    if len(order) != len(ids):
        raise GraphError("Граф пререквизитов содержит цикл.", [{"code": "CYCLE", "message": "Цикл в графе."}])
    return order


def _closure(start: int, adj: dict[int, list[int]]) -> set[int]:
    seen: set[int] = set()
    stack = list(adj.get(start, []))
    while stack:
        n = stack.pop()
        if n not in seen:
            seen.add(n)
            stack.extend(adj.get(n, []))
    return seen


# --------------------------------------------------------------------------- loading


def load_graph(db: Session, subject_id: int) -> Graph:
    topics = db.scalars(select(m.Topic).where(m.Topic.subject_id == subject_id)).all()
    nodes = {t.id: Node(t.id, t.code, t.name, t.subject_id, t.grade, t.order_index, t.priority) for t in topics}
    ids = list(nodes)
    rows = db.scalars(select(m.TopicPrerequisite).where(m.TopicPrerequisite.topic_id.in_(ids))
                      .order_by(m.TopicPrerequisite.id)).all() if ids else []
    edges = [Edge(r.prerequisite_id, r.topic_id, r.id, r.origin, r.review_status) for r in rows]
    return Graph(nodes, edges)


# --------------------------------------------------------------------------- diagnostics


def priority_score(mastery: float | None, priority: int, downstream: int, max_downstream: int, evidence: str,
                   target: float) -> dict[str, Any]:
    gap = 0.0 if mastery is None or target <= 0 else min(1.0, max(0.0, (target - mastery) / target))
    curriculum = (priority - 1) / 2
    dependency = downstream / max_downstream if max_downstream > 0 else 0.0
    ev = EVIDENCE_FACTOR.get(evidence, 0.0)
    score = 100 * ev * gap * (W_BASE + W_CURRICULUM * curriculum + W_DEPENDENCY * dependency)
    return {"score": round(score, 1), "components": {"gap": round(gap, 3), "curriculum": round(curriculum, 3),
                                                     "dependency": round(dependency, 3), "evidence": ev},
            "formula": "100 · evidence · gap · (0.6 + 0.2·curriculum + 0.2·dependency)"}


def diagnose(g: Graph, topic_stats: dict[int, dict[str, Any]], s: AnalysisSettings,
             grade: int | None = None) -> dict[str, Any]:
    """Graph nodes with diagnostics, edges, validation, chains. ``topic_stats`` = topic_analytics rows by id."""
    issues = validate_edges(g.nodes, g.edges)
    blocking = [i for i in issues if i["code"] in ("CYCLE", "SELF_PREREQUISITE", "UNKNOWN_TOPIC", "CROSS_SUBJECT")]
    in_scope = {i for i, n in g.nodes.items() if grade is None or n.grade == grade}
    approved = [e for e in g.approved() if e.prerequisite_id in g.nodes and e.topic_id in g.nodes
                and e.prerequisite_id != e.topic_id]
    # context nodes: prerequisites from other grades of the same subject that feed in-scope topics
    context = {e.prerequisite_id for e in approved if e.topic_id in in_scope and e.prerequisite_id not in in_scope}
    shown = in_scope | context
    down_adj: dict[int, list[int]] = {}
    up_adj: dict[int, list[int]] = {}
    for e in approved:
        if e.prerequisite_id in shown and e.topic_id in shown:
            down_adj.setdefault(e.prerequisite_id, []).append(e.topic_id)
            up_adj.setdefault(e.topic_id, []).append(e.prerequisite_id)
    for adj in (down_adj, up_adj):
        for k in adj:
            adj[k].sort(key=g.sort_key)
    if blocking:
        order = sorted(shown, key=g.sort_key)
    else:
        order = topological_order(Graph(g.nodes, approved), sorted(shown))
    # depth (longest prerequisite path) -> layered layout
    depth: dict[int, int] = {}
    for n in order:
        depth[n] = 0 if not up_adj.get(n) or blocking else 1 + max(depth.get(p, 0) for p in up_adj[n])

    status = {i: (topic_stats.get(i) or {}).get("status", "no_outcome_data") for i in shown}
    weak = {i for i in shown if status[i] in WEAK_STATUSES}
    descendants = {i: _closure(i, down_adj) & in_scope for i in shown} if not blocking else {i: set() for i in shown}
    ancestors = {i: _closure(i, up_adj) for i in shown} if not blocking else {i: set() for i in shown}
    max_down = max((len(descendants[i]) for i in in_scope), default=0)

    nodes_out = []
    for i in order:
        n = g.nodes[i]
        st = topic_stats.get(i) or {}
        ev = assess_topic(st, s) if st else {"category": "insufficient", "label": "Недостаточно данных",
                                              "reasons": ["Нет результатов по теме в выбранном срезе."],
                                              "allows_action": False}
        weak_down = sorted(descendants[i] & weak, key=g.sort_key)
        pr = priority_score(st.get("mastery"), n.priority, len(descendants[i]), max_down, ev["category"],
                            s.target_mastery)
        foundational = i in weak and bool(weak_down) and i in in_scope
        why = _why(n, st, ev, pr, weak_down, g, s, foundational)
        nodes_out.append({
            "topic_id": i, "code": n.code, "name": n.name, "grade": n.grade, "order": n.order,
            "curriculum_priority": n.priority, "in_scope": i in in_scope, "depth": depth.get(i, 0),
            "mastery": st.get("mastery"), "student_count": st.get("student_count", 0), "status": status[i],
            "gain_direction": ((st.get("gain") or {}).get("direction")), "hours": st.get("hours"),
            "evidence": {"category": ev["category"], "label": ev["label"], "reasons": ev["reasons"],
                         "allows_action": ev["allows_action"]},
            "prerequisites": sorted(up_adj.get(i, []), key=g.sort_key),
            "dependents": sorted(down_adj.get(i, []), key=g.sort_key),
            "ancestors": sorted(ancestors[i], key=g.sort_key),
            "descendants": sorted(descendants[i], key=g.sort_key),
            "downstream_count": len(descendants[i]), "weak_downstream": weak_down,
            "foundational_gap": foundational, "priority": pr, "why": why,
        })
    ranking = sorted([x for x in nodes_out if x["in_scope"] and x["priority"]["score"] > 0],
                     key=lambda x: (-x["priority"]["score"], g.sort_key(x["topic_id"])))
    edges_out = [{"id": e.id, "prerequisite_id": e.prerequisite_id, "topic_id": e.topic_id, "origin": e.origin,
                  "review_status": e.review_status,
                  "weak_link": e.prerequisite_id in weak and e.topic_id in weak}
                 for e in g.edges if e.topic_id in shown and e.prerequisite_id in g.nodes]
    return {
        "nodes": nodes_out, "edges": edges_out, "valid": not blocking, "issues": issues,
        "ranking": [{"topic_id": x["topic_id"], "name": x["name"], "score": x["priority"]["score"],
                     "foundational_gap": x["foundational_gap"]} for x in ranking],
        "chains": [] if blocking else critical_chains(order, up_adj, down_adj, weak, g, in_scope),
        "foundational_gaps": [x["topic_id"] for x in nodes_out if x["foundational_gap"]],
        "layers": max(depth.values(), default=0) + 1 if depth else 0,
        "heuristic": {"formula": "100 · evidence · gap · (0.6 + 0.2·curriculum + 0.2·dependency)",
                      "evidence_factor": EVIDENCE_FACTOR,
                      "note": "Эвристика ранжирования для методической проверки, а не модель, предсказывающая "
                              "результаты учеников."},
    }


def _why(n: Node, st: dict[str, Any], ev: dict[str, Any], pr: dict[str, Any], weak_down: list[int], g: Graph,
         s: AnalysisSettings, foundational: bool) -> list[str]:
    out: list[str] = []
    if st.get("mastery") is None:
        out.append("Освоение не рассчитано — приоритет не присваивается.")
    elif st["mastery"] < s.target_mastery:
        out.append(f"Освоение {st['mastery']}% ниже цели {s.target_mastery:g}% (разрыв "
                   f"{pr['components']['gap'] * 100:.0f}% от цели).")
    else:
        out.append(f"Освоение {st['mastery']}% не ниже цели {s.target_mastery:g}% — приоритет 0.")
    if foundational:
        names = ", ".join(f"«{g.nodes[i].name}»" for i in weak_down)
        out.append(f"Тема предшествует слабым темам {names}. Это структурная связь программы; причинное влияние на "
                   "их результаты данными не установлено.")
    elif weak_down:
        out.append("От темы зависят слабые темы.")
    if not ev["allows_action"]:
        out.append(f"{ev['label']}: автоматическое действие не предлагается — " + "; ".join(ev["reasons"]))
    elif ev["category"] == "exploratory":
        out.append("Данные предварительные (вес 0,6): " + "; ".join(ev["reasons"]))
    return out


def critical_chains(order: list[int], up_adj: dict[int, list[int]], down_adj: dict[int, list[int]], weak: set[int],
                    g: Graph, in_scope: set[int]) -> list[dict[str, Any]]:
    """Root-to-leaf prerequisite paths that contain ≥ 2 weak topics, most weak topics first (deterministic)."""
    roots = [i for i in order if not up_adj.get(i)]
    paths: list[list[int]] = []

    def walk(path: list[int]) -> None:
        if len(paths) >= 500:
            return
        nxt = down_adj.get(path[-1], [])
        if not nxt:
            paths.append(path)
            return
        for v in nxt:
            walk(path + [v])

    for r in roots:
        walk([r])
    chains = []
    for p in paths:
        w = [i for i in p if i in weak]
        if len(w) >= 2 and any(i in in_scope for i in p):
            chains.append({"path": p, "names": [g.nodes[i].name for i in p], "weak": w, "weak_count": len(w)})
    chains.sort(key=lambda c: (-c["weak_count"], -len(c["path"]), [g.sort_key(i) for i in c["path"]]))
    return chains[:MAX_CHAINS]


def check_new_edge(g: Graph, prerequisite_id: int, topic_id: int) -> list[dict[str, Any]]:
    """Issues that adding prerequisite → topic would create (empty list = the edge is safe to add)."""
    trial = Graph(g.nodes, [*g.edges, Edge(prerequisite_id, topic_id)])
    before = {(i["code"], i.get("topic_id"), i.get("prerequisite_id")) for i in validate_edges(g.nodes, g.edges)}
    return [i for i in validate_edges(trial.nodes, trial.edges)
            if (i["code"], i.get("topic_id"), i.get("prerequisite_id")) not in before or i["code"] == "CYCLE"]
