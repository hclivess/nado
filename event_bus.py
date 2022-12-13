import asyncio
import threading


class EventBus:
    _instance_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if not hasattr(EventBus, "_instance"):
            with EventBus._instance_lock:
                if not hasattr(EventBus, "_instance"):
                    EventBus._instance = object.__new__(cls)
                return EventBus._instance

    def __init__(self):
        self.listeners = {}

    def add_listener(self, event_name, listener):
        if not self.listeners.get(event_name, None):
            self.listeners[event_name] = {listener}
        else:
            self.listeners[event_name].add(listener)

    def remove_listener(self, event_name, listener):
        self.listeners[event_name].remove(listener)
        if len(self.listeners[event_name]) == 0:
            del self.listeners[event_name]

    def emit(self, event_name, event):
        listeners = self.listeners.get(event_name, [])
        for listener in listeners:
            asyncio.run(listener(event))
