"""Profile extraction for the agent: rules baseline (off the event loop) plus a computed completeness score."""

import asyncio
import time
from typing import List, Optional, Tuple

from models.agent_schemas import DetectedCase, ExtractionQuality
from models.schemas import ExtractionMetadata, StructuredCaseProfile
from services.extractor import extract_rules_only

EXTRACTOR_VERSION = "rules-1"
# The regex extractors use DOTALL patterns; cap the text they see so a pathological 2 MB upload can't stall a worker.
MAX_EXTRACT_CHARS = 300_000


def _bounded(text: str) -> str:
    if len(text) <= MAX_EXTRACT_CHARS:
        return text
    return text[: MAX_EXTRACT_CHARS * 2 // 3] + "\n" + text[-MAX_EXTRACT_CHARS // 3 :]


def extract_profile_sync(text: str) -> StructuredCaseProfile:
    started = time.perf_counter()
    profile = extract_rules_only(_bounded(text))
    # The legacy constant confidence (0.5 for rules) is kept so the schema and the model's expectations don't change;
    # the UI shows `assess_quality` instead, which actually reflects what was found.
    profile.metadata = ExtractionMetadata(
        extraction_method="rules", confidence=0.5, processing_time_ms=int((time.perf_counter() - started) * 1000)
    )
    return profile


async def extract_profile(text: str) -> StructuredCaseProfile:
    return await asyncio.to_thread(extract_profile_sync, text)


def assess_quality(profile: StructuredCaseProfile) -> ExtractionQuality:
    """Completeness = share of six things a downstream card needs that extraction actually found."""
    checks = {
        "parties": bool(profile.parties.petitioner and profile.parties.respondent),
        "court": bool(profile.court_level and profile.court_level.lower() != "unknown"),
        "legal issues": bool(profile.legal_issues),
        "statutes": bool(profile.ipc_sections or profile.acts_referenced),
        "key facts": len(profile.key_facts) >= 2,
        "relief sought": bool(profile.relief_sought),
    }
    found = sum(checks.values())
    completeness = round(found / len(checks), 2)
    quality = "good" if found >= 5 else "partial" if found >= 3 else "poor"
    method = profile.metadata.extraction_method if profile.metadata else "rules"
    missing: List[str] = [name for name, ok in checks.items() if not ok]
    return ExtractionQuality(method=method, quality=quality, completeness=completeness, missing=missing)  # type: ignore[arg-type]


def detect(profile: StructuredCaseProfile) -> DetectedCase:
    return DetectedCase(
        petitioner=profile.parties.petitioner, respondent=profile.parties.respondent,
        court_level=profile.court_level, sections=list(profile.ipc_sections[:8]),
    )


async def profile_and_quality(text: str) -> Tuple[StructuredCaseProfile, ExtractionQuality]:
    profile = await extract_profile(text)
    return profile, assess_quality(profile)


def profile_key(sha: str, override: Optional[StructuredCaseProfile] = None) -> str:
    from services.agent.workspace import artifact_key
    return artifact_key("profile", sha, EXTRACTOR_VERSION, override.model_dump_json() if override else None)
