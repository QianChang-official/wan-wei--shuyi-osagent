from pydantic import BaseModel, Field


class ResearchTechnology(BaseModel):
    id: str
    name: str
    source_level: str
    publication_status: str
    core_idea: str
    target_modules: list[str]
    adoption_ratio: float
    current_status: str
    v08_actions: list[str]
    v09_risk_controls: list[str]
    evidence_files: list[str]
    source_urls: list[str] = Field(default_factory=list)


class AdoptionRoute(BaseModel):
    route_id: str
    name_cn: str
    target_pillar: str
    backend_plan: list[str]
    frontend_plan: list[str]
    arena_plan: list[str]
    status: str
    expected_impact: str


class VersionMapping(BaseModel):
    version: str
    positioning: str
    authoritative_support: list[str]
    completed: list[str]
    unfinished: list[str]
    inherited_by: list[str]
    evidence_files: list[str]
