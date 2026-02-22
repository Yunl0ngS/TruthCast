from app.schemas.detect import ClaimItem
from app.services.pipeline import extract_claims
from app.skills.base import SkillContext


class ClaimExtractorSkill:
    name = "claim_extractor"

    def run(self, payload: str, context: SkillContext) -> list[ClaimItem]:
        context.metadata["last_skill"] = self.name
        return extract_claims(payload, strategy=context.strategy)
