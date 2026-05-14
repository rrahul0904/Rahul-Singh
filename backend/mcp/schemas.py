from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SafetyLevel(str, Enum):
    READ_ONLY = "READ_ONLY"
    PLANNING = "PLANNING"
    STAGING = "STAGING"
    EXECUTION_REQUIRES_APPROVAL = "EXECUTION_REQUIRES_APPROVAL"
    ADMIN_REQUIRES_APPROVAL = "ADMIN_REQUIRES_APPROVAL"


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    safety_level: SafetyLevel
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "safety_level": self.safety_level.value,
            "description": self.description,
            "input_schema": self.input_schema,
        }


@dataclass(frozen=True)
class ToolResult:
    tool_name: str
    status: str
    safety_level: SafetyLevel
    output: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "status": self.status,
            "safety_level": self.safety_level.value,
            "output": self.output,
        }
