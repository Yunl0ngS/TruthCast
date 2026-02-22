from app.schemas.detect import (
    ClaimItem,
    EvidenceItem,
    ReportResponse,
    SimulateResponse,
)
from app.services.pipeline import simulate_opinion
from app.skills.base import SkillContext


class OpinionSimulatorSkill:
    name = "opinion_simulator"

    def run(
        self,
        payload: tuple[
            str,
            int,
            str,
            list[str],
            list[ClaimItem] | None,
            list[EvidenceItem] | None,
            ReportResponse | None,
        ],
        context: SkillContext,
    ) -> SimulateResponse:
        context.metadata["last_skill"] = self.name
        (
            text,
            time_window_hours,
            platform,
            comments,
            claims,
            evidences,
            report,
        ) = payload
        return simulate_opinion(
            text=text,
            time_window_hours=time_window_hours,
            platform=platform,
            comments=comments,
            claims=claims,
            evidences=evidences,
            report=report,
        )
