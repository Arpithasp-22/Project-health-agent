"""
tree_builder.py
---------------
Layer 1 of the health engine — pure hierarchy reconstruction.

Converts a flat list of TaskRow objects into a tree of TreeNode objects
by inferring parent-child relationships from the depth/level column.

This module contains ZERO health logic. It only knows about structure.
It works for any project plan that carries a numeric depth indicator
in one of: Level, Ancestors, Outline Level, or equivalent.

Public API
----------
    build_tree(tasks: list[TaskRow]) -> TreeResult

    TreeResult.roots      : top-level nodes (no parent)
    TreeResult.all_nodes  : every node in the tree, flat list
    TreeResult.ambiguities: structural issues found during build
"""

from __future__ import annotations

import sys
from pathlib import Path
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dataclasses import dataclass, field
from typing import Any

from agent.parser import TaskRow


# ---------------------------------------------------------------------------
# TreeNode
# ---------------------------------------------------------------------------

@dataclass
class TreeNode:
    """
    One node in the reconstructed project tree.

    Carries the original TaskRow unchanged plus structural metadata
    added during tree construction.
    """
    # Original row data — passed through untouched
    task_row:   TaskRow

    # Tree structure
    level:      int                         # depth in tree (0 = root)
    parent:     "TreeNode | None" = None
    children:   list["TreeNode"] = field(default_factory=list)

    # Set by tree builder — not health flags
    node_type:  str = "unknown"             # "root" | "branch" | "leaf"
    row_index:  int = 0                     # position in original flat list

    # Ambiguity flags — structural issues only
    ambiguity_flags: list[str] = field(default_factory=list)

    # ── Convenience properties (delegates to task_row) ──

    @property
    def name(self) -> str:
        return self.task_row.task_name

    @property
    def status(self) -> str:
        return self.task_row.status

    @property
    def pct_complete(self) -> float:
        return self.task_row.pct_complete

    @property
    def schedule_health(self) -> str:
        return self.task_row.schedule_health

    @property
    def is_critical(self) -> bool:
        return self.task_row.is_critical

    @property
    def is_on_hold(self) -> bool:
        return self.task_row.is_on_hold or self.task_row.status == "On Hold"

    @property
    def is_at_risk(self) -> bool:
        return self.task_row.is_at_risk

    @property
    def has_owner(self) -> bool:
        return self.task_row.assigned_to is not None

    @property
    def start_date(self):
        return self.task_row.start_date

    @property
    def end_date(self):
        return self.task_row.end_date

    @property
    def is_leaf(self) -> bool:
        return len(self.children) == 0

    def add_child(self, child: "TreeNode") -> None:
        self.children.append(child)
        child.parent = self

    def descendants(self) -> list["TreeNode"]:
        """Return all descendants in depth-first order."""
        result: list[TreeNode] = []
        for child in self.children:
            result.append(child)
            result.extend(child.descendants())
        return result

    def leaves(self) -> list["TreeNode"]:
        """Return all leaf descendants."""
        if self.is_leaf:
            return [self]
        result: list[TreeNode] = []
        for child in self.children:
            result.extend(child.leaves())
        return result

    def depth_from_root(self) -> int:
        """How many levels down from the root of this subtree."""
        if self.parent is None:
            return 0
        return 1 + self.parent.depth_from_root()

    def phase_ancestor(self) -> "TreeNode | None":
        """
        Walk up the tree and return the nearest ancestor that is NOT
        a leaf (i.e. a summary/phase node). Returns None if already
        at the root.
        """
        node = self.parent
        while node is not None:
            if not node.is_leaf:
                return node
            node = node.parent
        return None

    def __repr__(self) -> str:
        return (
            f"TreeNode(level={self.level}, "
            f"name={self.name!r}, "
            f"children={len(self.children)}, "
            f"type={self.node_type})"
        )


# ---------------------------------------------------------------------------
# TreeResult
# ---------------------------------------------------------------------------

@dataclass
class TreeResult:
    """Output of build_tree()."""
    roots:       list[TreeNode]        # top-level nodes (no parent)
    all_nodes:   list[TreeNode]        # every node, flat, in original order
    ambiguities: list[str]             # structural warnings
    depth_col_used: str                # which column was used for depth

    @property
    def scoreable_roots(self) -> list[TreeNode]:
        """
        Roots that have at least one descendant.
        Roots with no descendants are flagged as ambiguous and not scored.
        """
        return [r for r in self.roots if not r.is_leaf]

    @property
    def ambiguous_roots(self) -> list[TreeNode]:
        """Roots with no descendants — cannot be scored."""
        return [r for r in self.roots if r.is_leaf]


# ---------------------------------------------------------------------------
# Build algorithm
# ---------------------------------------------------------------------------

def build_tree(tasks: list[TaskRow]) -> TreeResult:
    """
    Convert a flat list of TaskRow objects into a tree of TreeNode objects.

    Parent-child relationships are inferred from the `ancestors` field on
    each TaskRow, which is populated by the parser from whichever depth
    column exists in the source file (Level, Ancestors, Outline Level, etc.).

    Algorithm
    ---------
    Maintain a stack: {level → most_recent_node_at_that_level}

    For each row:
        node.level = row.ancestors
        parent = stack.get(node.level - 1)
        if parent exists → attach as child
        else → node is a root
        stack[node.level] = node
        clear all stack entries deeper than node.level

    This correctly handles:
        - Single-level flat lists (all level 0)
        - Deep nesting (0 → 1 → 2 → 3 → ...)
        - Mixed depth (level gaps, e.g. 0 → 2)
        - Multiple top-level roots in one file
    """
    if not tasks:
        return TreeResult(
            roots=[],
            all_nodes=[],
            ambiguities=["No tasks found in file"],
            depth_col_used="none",
        )

    roots:       list[TreeNode] = []
    all_nodes:   list[TreeNode] = []
    ambiguities: list[str]      = []

    # stack[level] = most recent TreeNode at that level
    stack: dict[int, TreeNode] = {}

    for i, task in enumerate(tasks):
        level = task.ancestors   # already normalised by parser

        node = TreeNode(
            task_row  = task,
            level     = level,
            row_index = i,
        )
        all_nodes.append(node)

        parent_level = level - 1

        if parent_level >= 0 and parent_level in stack:
            parent = stack[parent_level]
            parent.add_child(node)
        else:
            # No parent found at the expected level
            if parent_level >= 0:
                # Level gap — expected a parent but didn't find one
                # Look for the nearest ancestor in the stack
                nearest = None
                for lvl in sorted(stack.keys(), reverse=True):
                    if lvl < level:
                        nearest = stack[lvl]
                        break

                if nearest is not None:
                    nearest.add_child(node)
                    node.ambiguity_flags.append(
                        f"level_gap: expected parent at level {parent_level}, "
                        f"attached to level {nearest.level} instead"
                    )
                    ambiguities.append(
                        f"'{node.name}': level gap detected "
                        f"(level {level}, nearest parent at level {nearest.level})"
                    )
                else:
                    roots.append(node)
            else:
                roots.append(node)

        # Update stack: this node is now the most recent at its level
        stack[level] = node

        # Clear all stack entries deeper than current level
        for k in list(stack.keys()):
            if k > level:
                del stack[k]

    # ── Classify node types ──
    for node in all_nodes:
        if node.parent is None:
            node.node_type = "root"
        elif node.is_leaf:
            node.node_type = "leaf"
        else:
            node.node_type = "branch"

    # ── Flag roots with no descendants ──
    for root in roots:
        if root.is_leaf:
            root.ambiguity_flags.append("no_descendants")
            ambiguities.append(
                f"'{root.name}': root node with no descendants — "
                f"cannot be scored from child tasks"
            )

    return TreeResult(
        roots          = roots,
        all_nodes      = all_nodes,
        ambiguities    = ambiguities,
        depth_col_used = "ancestors",
    )


# ---------------------------------------------------------------------------
# Utility: map comment row-references to tree nodes
# ---------------------------------------------------------------------------

def map_comments_to_nodes(
    all_nodes: list[TreeNode],
    comments: list[Any],           # list[CommentEntry]
    row_offset: int = 2,           # Excel header = row 1, data starts row 2
) -> dict[int, list[str]]:
    """
    Match comments to tree nodes by row reference.

    Comments in the Comments sheet reference rows by number
    (e.g. "Row 292"). The row number maps to the node's position
    in the original flat task list (row_index + row_offset).

    Returns: {node_index: [comment_text, ...]}
    """
    index_to_comments: dict[int, list[str]] = {}

    for comment in comments:
        ref = comment.row_ref  # e.g. "Row 292"
        if not ref:
            continue

        # Parse the row number from the reference string
        import re
        m = re.search(r"\d+", str(ref))
        if not m:
            continue

        excel_row = int(m.group())
        # Convert Excel row number to node index
        # Excel row 2 = first data row = node index 0
        node_idx = excel_row - row_offset

        if 0 <= node_idx < len(all_nodes):
            if node_idx not in index_to_comments:
                index_to_comments[node_idx] = []
            if comment.text:
                index_to_comments[node_idx].append(comment.text)

    return index_to_comments


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from agent.parser import parse_projects_from_file

    files = [
        Path(__file__).parent.parent / "Project Plan B.xlsx",
        Path(__file__).parent.parent / "S2P Project.xlsx",
    ]

    for f in files:
        print(f"\n{'='*60}")
        print(f"FILE: {f.name}")
        all_projects = parse_projects_from_file(f)

        # Build one tree per project's task list
        for proj in all_projects:
            result = build_tree(proj.tasks)
            print(f"\n  Project slice: {proj.meta.project_name}")
            print(f"  Total nodes : {len(result.all_nodes)}")
            print(f"  Roots       : {len(result.roots)}")
            print(f"  Scoreable   : {len(result.scoreable_roots)}")
            print(f"  Ambiguities : {result.ambiguities[:2]}")

            for root in result.scoreable_roots[:3]:
                print(f"\n    ROOT: {root.name}")
                for child in root.children[:4]:
                    prefix = "    " if child.is_leaf else "  + "
                    print(f"      {prefix}{child.name} "
                          f"[{child.node_type}] "
                          f"children={len(child.children)}")
