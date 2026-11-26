"""Technology-neutral element model shared by every back end."""
from __future__ import annotations

from typing import Hashable, Iterable, List, Optional, Sequence, Tuple

Rect = Tuple[int, int, int, int]  # left, top, right, bottom in physical screen pixels


class Node:
    """One UI element. Back ends subclass this.

    Implementations should cache anything expensive: the search engine calls
    ``role()`` and ``get()`` many times on the same node.
    """

    tech: str = "abstract"

    # --- identity -----------------------------------------------------------------
    def key(self) -> Hashable:
        raise NotImplementedError

    def __eq__(self, other):
        return isinstance(other, Node) and other.tech == self.tech and other.key() == self.key()

    def __hash__(self):
        return hash((self.tech, self.key()))

    # --- data ---------------------------------------------------------------------
    def role(self) -> str:
        raise NotImplementedError

    def get(self, name: str) -> Optional[str]:
        """Value of a selector attribute (None when absent)."""
        return self.selector_attrs().get(name)

    def selector_attrs(self) -> dict:
        """All attributes that may be used in a selector, most useful first."""
        return {}

    def suggested_attrs(self, is_top: bool = False) -> List[str]:
        """Attribute names the generator should try for this node, best first."""
        return []

    def properties(self) -> List[Tuple[str, str, str]]:
        """Full property grid rows: (group, name, value)."""
        return [("Selector", k, v) for k, v in self.selector_attrs().items()]

    def label(self) -> str:
        name = self.get("name") or ""
        return f"{self.role()}  \"{name[:60]}\"" if name else self.role()

    def rect(self) -> Optional[Rect]:
        return None

    # --- tree ---------------------------------------------------------------------
    def children(self) -> List["Node"]:
        return []

    def parent(self) -> Optional["Node"]:
        return None

    def is_root(self) -> bool:
        return self.parent() is None

    def find(self, step, deep: bool, budget) -> Optional[List["Node"]]:
        """Optional fast path for the search engine.

        Return the nodes under ``self`` (children, or all descendants when
        ``deep``) that *may* match ``step``; the engine still checks every
        returned node. Return ``None`` to let the engine walk ``children()``.
        """
        return None

    def ancestry(self) -> List["Node"]:
        """Ancestors from just below the root down to and including self."""
        chain = [self]
        cur = self.parent()
        guard = 0
        while cur is not None and not cur.is_root() and guard < 500:
            chain.append(cur)
            cur = cur.parent()
            guard += 1
        chain.reverse()
        return chain


class Backend:
    tech: str = "abstract"
    title: str = "Abstract"

    def root(self) -> Node:
        raise NotImplementedError

    def from_point(self, x: int, y: int) -> Optional[Node]:
        return None

    def available(self) -> Tuple[bool, str]:
        return True, ""


def walk(node: Node, budget) -> Iterable[Node]:
    """Pre-order descendants of ``node`` (not including it)."""
    stack: List[Sequence[Node]] = [list(node.children())]
    idx = [0]
    while stack:
        level = stack[-1]
        i = idx[-1]
        if i >= len(level):
            stack.pop()
            idx.pop()
            continue
        idx[-1] = i + 1
        child = level[i]
        budget.tick()
        yield child
        kids = child.children()
        if kids:
            stack.append(list(kids))
            idx.append(0)
