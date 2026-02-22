from app.orchestrator.engine import OrchestratorEngine
from app.orchestrator.registry import SkillRegistry
from app.skills import (
    ClaimExtractorSkill,
    EvidenceRetrieverSkill,
    OpinionSimulatorSkill,
    ReportBuilderSkill,
)


def build_orchestrator() -> OrchestratorEngine:
    registry = SkillRegistry()
    registry.register(ClaimExtractorSkill())
    registry.register(EvidenceRetrieverSkill())
    registry.register(ReportBuilderSkill())
    registry.register(OpinionSimulatorSkill())
    return OrchestratorEngine(registry=registry)


orchestrator = build_orchestrator()
