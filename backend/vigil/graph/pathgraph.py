"""PathGraph — the unified financial graph, kept in memory and updated incrementally.

Nodes: accounts (customer/external) and devices. Edges: completed money
movements only (ledger postings). Journey events are NOT graph nodes.

Built once from SQLite at startup / reset; every settled payment calls
`add_transaction` (O(1)). Nothing rebuilds the graph per request.
"""

from __future__ import annotations

from bisect import bisect_left, insort
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from vigil import clock, db


@dataclass(frozen=True, slots=True)
class Edge:
    tx_id: str
    seq: int
    src: str
    dst: str
    amount_paise: int
    ts: str
    t: float          # epoch seconds, for fast windows
    kind: str


def _t(edge: Edge) -> float:
    return edge.t


def _push(edges: list[Edge], edge: Edge) -> None:
    """Keep every per-account list chronological (window queries bisect on t)."""
    if edges and edge.t < edges[-1].t:
        insort(edges, edge, key=_t)   # a back-dated posting; ties keep posting order
    else:
        edges.append(edge)


class PathGraph:
    def __init__(self) -> None:
        self.clear()

    def clear(self) -> None:
        self.out_edges: dict[str, list[Edge]] = defaultdict(list)
        self.in_edges: dict[str, list[Edge]] = defaultdict(list)
        self.account_devices: dict[str, set[str]] = defaultdict(set)
        self.device_accounts: dict[str, set[str]] = defaultdict(set)
        self.accounts: dict[str, dict] = {}
        self.version = 0

    # ── building ───────────────────────────────────────────────────────
    def load(self) -> "PathGraph":
        self.clear()
        for row in db.q("SELECT id, display_name, kind, opened_at, persona FROM accounts"):
            self.accounts[row["id"]] = row
        for row in db.q("SELECT account_id, device_id FROM account_devices"):
            self._link_device(row["account_id"], row["device_id"])
        for row in db.q(
            "SELECT id, seq, sender_id, recipient_id, amount_paise, ts, kind "
            "FROM transactions ORDER BY seq"
        ):
            self._append(row)
        self.version += 1
        return self

    def _link_device(self, account_id: str, device_id: str) -> None:
        self.account_devices[account_id].add(device_id)
        self.device_accounts[device_id].add(account_id)

    def _append(self, row: dict) -> None:
        if row["kind"] == "opening":
            return  # opening balances are bookkeeping, not behaviour
        edge = Edge(
            tx_id=row["id"], seq=row["seq"], src=row["sender_id"], dst=row["recipient_id"],
            amount_paise=int(row["amount_paise"]), ts=row["ts"],
            t=clock.parse(row["ts"]).timestamp(), kind=row["kind"],
        )
        _push(self.out_edges[edge.src], edge)
        _push(self.in_edges[edge.dst], edge)

    def add_transaction(self, row: dict) -> None:
        self._append(row)
        self.version += 1

    def add_device(self, account_id: str, device_id: str) -> None:
        self._link_device(account_id, device_id)
        self.version += 1

    def add_account(self, row: dict) -> None:
        self.accounts[row["id"]] = row
        self.version += 1

    # ── queries ────────────────────────────────────────────────────────
    def inflows(self, account_id: str, since_t: float | None = None) -> list[Edge]:
        edges = self.in_edges.get(account_id, [])
        return edges if since_t is None else edges[bisect_left(edges, since_t, key=_t):]

    def outflows(self, account_id: str, since_t: float | None = None) -> list[Edge]:
        edges = self.out_edges.get(account_id, [])
        return edges if since_t is None else edges[bisect_left(edges, since_t, key=_t):]

    def inflows_before(self, account_id: str, before_t: float) -> list[Edge]:
        edges = self.in_edges.get(account_id, [])
        return edges[:bisect_left(edges, before_t, key=_t)]

    def outflows_before(self, account_id: str, before_t: float) -> list[Edge]:
        edges = self.out_edges.get(account_id, [])
        return edges[:bisect_left(edges, before_t, key=_t)]

    def neighbours(self, account_id: str, since_t: float | None = None) -> set[str]:
        out = {e.dst for e in self.outflows(account_id, since_t)}
        inn = {e.src for e in self.inflows(account_id, since_t)}
        return (out | inn) - {account_id}

    def device_peers(self, account_id: str) -> set[str]:
        peers: set[str] = set()
        for device in self.account_devices.get(account_id, ()):
            peers |= self.device_accounts.get(device, set())
        return peers

    def has_cycle_through(self, account_id: str, since_t: float, max_hops: int) -> list[str] | None:
        """Bounded DFS along time-windowed outflows; returns the cycle path if any."""
        stack: list[tuple[str, list[str]]] = [(account_id, [account_id])]
        while stack:
            node, path = stack.pop()
            if len(path) > max_hops:
                continue
            for edge in self.outflows(node, since_t):
                if edge.dst == account_id and len(path) >= 2:
                    return path + [account_id]
                if edge.dst not in path:
                    stack.append((edge.dst, path + [edge.dst]))
        return None

    def edges_between(self, nodes: Iterable[str]) -> list[Edge]:
        keep = set(nodes)
        found: list[Edge] = []
        for node in keep:
            for edge in self.out_edges.get(node, []):
                if edge.dst in keep:
                    found.append(edge)
        return found

    def last_activity_before(self, account_id: str, before_t: float) -> float | None:
        latest: float | None = None
        for edges in (self.out_edges.get(account_id, []), self.in_edges.get(account_id, [])):
            i = bisect_left(edges, before_t, key=_t)
            if i and (latest is None or edges[i - 1].t > latest):
                latest = edges[i - 1].t
        return latest


GRAPH = PathGraph()
