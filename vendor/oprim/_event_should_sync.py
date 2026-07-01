"""event_should_sync — decide whether an Event passes a list of Filters."""
from __future__ import annotations

from ._hicode_types import Event, Filter


def event_should_sync(event: Event, *, filters: list[Filter]) -> bool:
    """Return ``True`` if *event* matches at least one :class:`Filter` in *filters*.

    Rules:
    - Empty *filters* list → ``False``.
    - A filter with ``type=None`` matches any event type.
    - A filter with a non-None ``type`` matches only when it equals
      ``event.type``.
    - Returns ``True`` as soon as the first matching filter is found.
    """
    if not filters:
        return False

    for f in filters:
        if not isinstance(f, Filter):
            continue
        if f.type is None or f.type == event.type:
            return True

    return False
