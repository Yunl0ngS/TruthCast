from typing import Any


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, Any] = {}

    def register(self, skill: Any) -> None:
        self._skills[skill.name] = skill

    def get(self, name: str) -> Any:
        if name not in self._skills:
            raise KeyError(f"Skill not found: {name}")
        return self._skills[name]
