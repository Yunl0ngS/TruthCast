from app.schemas.detect import ClaimItem, EvidenceItem
from app.services.pipeline import retrieve_evidence
from app.skills.base import SkillContext


class EvidenceRetrieverSkill:
    name = "evidence_retriever"

    def run(self, payload: list[ClaimItem], context: SkillContext) -> list[EvidenceItem]:
        context.metadata["last_skill"] = self.name
        return retrieve_evidence(payload, strategy=context.strategy)
