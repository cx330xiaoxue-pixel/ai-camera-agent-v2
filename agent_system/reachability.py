"""External reachability boundary only. No kinematics or motion compilation."""

from typing import Literal, Protocol

from .models import ContractModel, Identifier, TargetTrajectory


class ReachabilityResult(ContractModel):
    status: Literal["REACHABLE", "UNREACHABLE", "UNKNOWN"]
    reason: Identifier


class ReachabilityValidator(Protocol):
    def validate(self, trajectory: TargetTrajectory) -> ReachabilityResult: ...
