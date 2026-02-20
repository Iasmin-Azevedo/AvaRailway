from typing import Callable, Dict, List, Any

class EventManager:
    def __init__(self):
        self.listeners: Dict[str, List[Callable]] = {}

    def subscribe(self, event_type: str, listener: Callable):
        if event_type not in self.listeners:
            self.listeners[event_type] = []
        self.listeners[event_type].append(listener)

    async def notify(self, event_type: str, data: Any, db=None):
        if event_type in self.listeners:
            for listener in self.listeners[event_type]:
                await listener(data, db)

event_manager = EventManager()