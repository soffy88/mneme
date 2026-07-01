"""oprim.graph_traversal — Generic BFS/DFS graph traversal.

3O layer: oprim (single atomic traversal call, pure logic, cross-business reusable).
Works with any adjacency representation via callable. Used by AII and Stratum concept graph.
"""

from __future__ import annotations

from collections import deque
from typing import Callable


def graph_traversal(
    *,
    start_nodes: list[str],
    get_neighbors: Callable[[str], list[str]],
    mode: str = "bfs",  # "bfs" | "dfs"
    max_depth: int = 5,
    max_nodes: int = 1000,
) -> dict:
    """Traverse a graph from start nodes via BFS or DFS.

    get_neighbors: callable(node_id) -> list of neighbor node_ids
    Returns: {
        visited: list[str],  # in traversal order
        depth_map: {node_id: int},  # distance from start
        edges_traversed: list[tuple[str,str]],
        truncated: bool,  # True if max_nodes hit
    }
    """
    visited: list[str] = []
    depth_map: dict[str, int] = {}
    edges_traversed: list[tuple[str, str]] = []
    truncated = False

    if not start_nodes:
        return {
            "visited": visited,
            "depth_map": depth_map,
            "edges_traversed": edges_traversed,
            "truncated": truncated,
        }

    seen: set[str] = set()

    if mode == "bfs":
        queue: deque[tuple[str, int]] = deque()
        for node in start_nodes:
            if node not in seen:
                seen.add(node)
                queue.append((node, 0))
                visited.append(node)
                depth_map[node] = 0

        while queue:
            if len(visited) >= max_nodes:
                truncated = True
                break
            node, depth = queue.popleft()
            if depth >= max_depth:
                continue
            neighbors = get_neighbors(node)
            for neighbor in neighbors:
                if neighbor not in seen:
                    seen.add(neighbor)
                    edges_traversed.append((node, neighbor))
                    new_depth = depth + 1
                    depth_map[neighbor] = new_depth
                    visited.append(neighbor)
                    if len(visited) >= max_nodes:
                        truncated = True
                        break
                    queue.append((neighbor, new_depth))
            if truncated:
                break

    elif mode == "dfs":
        # Iterative DFS using explicit stack
        stack: list[tuple[str, int, str | None]] = []
        for node in reversed(start_nodes):
            if node not in seen:
                stack.append((node, 0, None))

        while stack:
            if len(visited) >= max_nodes:
                truncated = True
                break
            node, depth, parent = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            visited.append(node)
            depth_map[node] = depth
            if parent is not None:
                edges_traversed.append((parent, node))
            if depth < max_depth:
                neighbors = get_neighbors(node)
                for neighbor in reversed(neighbors):
                    if neighbor not in seen:
                        stack.append((neighbor, depth + 1, node))

    return {
        "visited": visited,
        "depth_map": depth_map,
        "edges_traversed": edges_traversed,
        "truncated": truncated,
    }
