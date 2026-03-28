"""Pydantic models for structured analysis output."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class CompanyMention(BaseModel):
    name: str
    ticker: Optional[str] = None
    sentiment: Literal["bullish", "bearish", "neutral", "mixed"]
    conviction: int = 3                # 1-5: how strong is this call
    thesis: str                        # what changed + why it matters
    speaker: Optional[str] = None
    context_quote: str
    approximate_location: str


class MacroCall(BaseModel):
    theme: str
    position: str
    conviction: int = 3                # 1-5
    what_changed: str = ""             # the delta — what's new about this call
    speaker: Optional[str] = None
    context_quote: str
    approximate_location: str


class ContentHook(BaseModel):
    headline: str
    insight: str
    angle: str
    content_pillar: str
    conviction: int = 3
    context_quote: str
    why_it_matters: str


class PersonMention(BaseModel):
    name: str
    context: str
    sentiment: str


class MarketingTactic(BaseModel):
    tactic: str
    platform: Optional[str] = None
    result_cited: Optional[str] = None
    applicable_to: str
    conviction: int = 3
    speaker: Optional[str] = None
    context_quote: str


class EpisodeAnalysis(BaseModel):
    episode_id: str
    podcast_name: str
    episode_title: str
    audience: str
    one_sentence_summary: str
    topic_tags: list[str] = Field(default_factory=list)
    companies: list[CompanyMention] = Field(default_factory=list)
    macro_calls: list[MacroCall] = Field(default_factory=list)
    content_hooks: list[ContentHook] = Field(default_factory=list)
    marketing_tactics: list[MarketingTactic] = Field(default_factory=list)
    people_mentioned: list[PersonMention] = Field(default_factory=list)
    contrarian_takes: list[str] = Field(default_factory=list)
    why_it_matters_mark: Optional[str] = None
    why_it_matters_brooke: Optional[str] = None
    analyzed_at: datetime = Field(default_factory=datetime.utcnow)
