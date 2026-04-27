from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

TraceEventType = Literal[
    "assistant_message",
    "tool_call",
    "tool_result",
    "file_op",
    "network_op",
    "memory_op",
    "cron_op",
    "config_op",
    "skill_op",
    "gateway_send",
    "decision",
]
TraceScope = Literal["mock", "static", "production"]

_ALLOWED_TYPES = {
    "assistant_message",
    "tool_call",
    "tool_result",
    "file_op",
    "network_op",
    "memory_op",
    "cron_op",
    "config_op",
    "skill_op",
    "gateway_send",
    "decision",
}
_ALLOWED_SCOPES = {"mock", "static", "production"}


@dataclass(frozen=True)
class TraceEvent:
    type: TraceEventType
    name: str
    scope: TraceScope = "mock"
    args: Mapping[str, Any] = field(default_factory=dict)
    result: Any = None
    index: int | None = None
    note: str | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any], *, index: int) -> "TraceEvent":
        event_type = data.get("type")
        scope = data.get("scope", "mock")
        if event_type not in _ALLOWED_TYPES:
            raise ValueError(f"unknown trace event type: {event_type!r}")
        if scope not in _ALLOWED_SCOPES:
            raise ValueError(f"unknown trace event scope: {scope!r}")
        name = data.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("trace event name must be a non-empty string")
        args = data.get("args", {})
        if args is None:
            args = {}
        if not isinstance(args, Mapping):
            raise ValueError("trace event args must be a mapping")
        return cls(
            type=event_type,
            name=name,
            scope=scope,
            args=dict(args),
            result=data.get("result"),
            index=data.get("index", index),
            note=data.get("note"),
        )

    def to_metadata(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "name": self.name,
            "scope": self.scope,
            "index": self.index,
        }

    def to_dict(self, *, include_payload: bool = False) -> dict[str, Any]:
        data = self.to_metadata()
        if self.note is not None:
            data["note"] = self.note
        if include_payload:
            data["args"] = dict(self.args)
            data["result"] = self.result
        return data


@dataclass(frozen=True)
class Trace:
    events: tuple[TraceEvent, ...] = ()

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> "Trace":
        if not data:
            return cls()
        raw_events = data.get("events", [])
        if raw_events is None:
            raw_events = []
        if not isinstance(raw_events, list):
            raise ValueError("trace.events must be a list")
        return cls(tuple(TraceEvent.from_mapping(event, index=i) for i, event in enumerate(raw_events)))

    def by_type(self, event_type: TraceEventType) -> tuple[TraceEvent, ...]:
        return tuple(event for event in self.events if event.type == event_type)

    def tool_calls(self) -> tuple[TraceEvent, ...]:
        return self.by_type("tool_call")

    def final_message(self) -> str:
        for event in reversed(self.events):
            if event.type == "assistant_message":
                return "" if event.result is None else str(event.result)
        return ""

    def to_metadata(self) -> dict[str, Any]:
        return {"events": [event.to_metadata() for event in self.events]}

    def to_dict(self, *, include_payload: bool = False) -> dict[str, Any]:
        return {"events": [event.to_dict(include_payload=include_payload) for event in self.events]}
