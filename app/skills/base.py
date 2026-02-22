from dataclasses import dataclass, field
from typing import Any, Protocol

from app.schemas.detect import StrategyConfig


@dataclass
class SkillContext:
    metadata: dict[str, Any] = field(default_factory=dict)
    strategy: StrategyConfig | None = None


class Skill(Protocol):
    name: str

    def run(self, payload: Any, context: SkillContext) -> Any:
        ...
