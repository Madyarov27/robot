"""What the robot can *do*, as opposed to say.

The model picks between answering and acting. Questions ("what is pi to four
digits") never touch this file — the model just answers. Only physical verbs
land here, because those are the ones an LLM cannot do by itself.

Note what is deliberately absent: there is no "repeat what I say next" skill.
The chat history already holds that instruction, so the model does it natively
on the following turn. Modes you can get for free are modes not worth building.
"""
from __future__ import annotations

import json

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "go_to",
            "description": "Drive to a named place in the house, e.g. the corridor or the kitchen.",
            "parameters": {
                "type": "object",
                "properties": {"place": {"type": "string", "description": "Name of the place."}},
                "required": ["place"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explore",
            "description": "Wander the house freely until told to stop.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stop",
            "description": "Stop moving immediately and cancel the current task.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remember_here",
            "description": "Give the robot's current spot a name, so it can be asked to return later.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "where_am_i",
            "description": "Report the robot's current position, what it is doing, and the places it knows.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


class Skills:
    """Dispatches tool calls to the navigator. Never blocks: navigation runs on
    its own thread, so the robot answers 'heading there now' and *then* goes."""

    def __init__(self, navigator) -> None:
        self.nav = navigator

    def run(self, name: str, arguments: str) -> str:
        try:
            args = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError:
            return "I couldn't understand that instruction."

        handler = getattr(self, f"_{name}", None)
        if handler is None:
            return f"I don't have a '{name}' skill."
        try:
            return handler(**args)
        except TypeError as exc:
            return f"Wrong arguments for {name}: {exc}"

    # -- skills ---------------------------------------------------------
    def _go_to(self, place: str) -> str:
        return self.nav.go_to(place)

    def _explore(self) -> str:
        return self.nav.explore()

    def _stop(self) -> str:
        return self.nav.cancel()

    def _remember_here(self, name: str) -> str:
        return self.nav.remember_here(name)

    def _where_am_i(self) -> str:
        # A vision-only robot has no coordinates to report — it says what it sees.
        if not getattr(self.nav, "grid", None):
            return (f"I can see: {self.nav.last_seen}. Currently {self.nav.status}.")
        name, dist = self.nav.nearest_place()
        where = "somewhere unfamiliar"
        if name:
            where = f"at the {name}" if dist < 1.5 else f"about {dist * 0.5:.1f} m from the {name}"
        known = ", ".join(sorted(self.nav.grid.places)) or "nowhere"
        return f"I am {where}. Currently {self.nav.status}. Places I know: {known}."
