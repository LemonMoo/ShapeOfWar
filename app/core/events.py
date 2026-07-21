"""Tiny pub/sub hub.

Every system talks through this so new features (economy, diplomacy AI, sound,
turns) can hook in without editing existing code. Subscribe with ``bus.on``,
publish with ``bus.emit``.
"""
from collections import defaultdict


class EventBus:
    def __init__(self):
        self._listeners = defaultdict(set)

    def on(self, event_type, fn):
        self._listeners[event_type].add(fn)
        return lambda: self.off(event_type, fn)  # unsubscribe handle

    def off(self, event_type, fn):
        self._listeners.get(event_type, set()).discard(fn)

    def emit(self, event_type, payload=None):
        for fn in list(self._listeners.get(event_type, ())):
            fn(payload)
        for fn in list(self._listeners.get("*", ())):
            fn({"type": event_type, "payload": payload})


# Single shared bus for the whole app.
bus = EventBus()
