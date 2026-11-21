"""Output schemas (Pydantic) – the skills' contract, enforced in code."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Category = Literal["composition", "value", "color", "brushwork and edges", "focal point and mood"]


class CategoryScore(BaseModel):
    name: Category
    score: int = Field(ge=1, le=10, description="Score from 1 to 10")
    observation: str = Field(description="What you SEE in the image (observation), with measured data where available")
    reasoning: str = Field(description="What you CONCLUDE from it (interpretation)")


class Suggestion(BaseModel):
    title: str
    how: str = Field(description="A concrete, actionable step for the painter")
    priority: int = Field(ge=1, le=3, description="1 = most important")


class AreaCheck(BaseModel):
    area: str = Field(description="A main part of the painting (e.g. 'face', 'robe/fabric', 'background')")
    assessment: str = Field(description="Form, light direction, material and edges in this area – honest, "
                                        "name what does NOT work as well")


class WeakestArea(BaseModel):
    area: str = Field(description="A concrete part of THIS painting (e.g. 'the robe's folds', 'the left background'), "
                                  "not a category name")
    problem: str = Field(description="What looks unconvincing there and why (form, light logic, material, edges…)")


class CritiqueResult(BaseModel):
    overall_impression: str
    area_review: list[AreaCheck] = Field(min_length=2, max_length=4,
                                         description="Walk through the main areas BEFORE picking the weakest")
    weakest_area: WeakestArea = Field(description="The single least convincing area; suggestion #1 addresses it")
    strengths: list[str] = Field(min_length=1, max_length=3)
    categories: list[CategoryScore] = Field(min_length=5, max_length=5)
    suggestions: list[Suggestion] = Field(min_length=1, max_length=3)
    style_respected: str = Field(description="How the critique took the work's own style/intent into account")
    limitations: str = Field(description="What cannot be judged from a photo (e.g. texture, size, true colors)")


class Reference(BaseModel):
    id: str = Field(description="The identifier returned by the search_museum tool (e.g. met-436535)")
    why: str = Field(description="Why it is relevant to this painting")
    what_to_study: str = Field(description="What is worth observing/learning from it")


class ReferenceResult(BaseModel):
    summary: str = Field(description="Short description: what was searched for and why")
    references: list[Reference] = Field(max_length=4, description="0–4 works; empty if no search result truly fits")
    study_exercise: str = Field(description="One concrete practice exercise based on the references")


class InjectionCheck(BaseModel):
    has_text: bool
    text: str = Field(description="Text readable in the image (empty if none)")
    addressed_to_ai: bool = Field(description="Is the text an instruction to an AI/evaluator?")
    explanation: str


OUTPUT_MODELS: dict[str, type[BaseModel]] = {
    "critique": CritiqueResult,
    "references": ReferenceResult,
}
