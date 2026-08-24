"""Deterministic preparation and reconciliation of audit atom proposals."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from hashlib import sha256
import json
import re


_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9]+")


@dataclass(frozen=True)
class ModelComparisonDraft:
    title: str
    digital_product: str
    work_type: str | None
    object_type: str | None
    source_clause: str
    notes: str | None
    source_refs: list[dict]
    model_variants: list[dict]
    source_fingerprint: str
    confidence_percent: int | None
    agreement_count: int
    registry_count: int
    sort_order: int


def _normalized_title(value: str) -> str:
    return " ".join(_WORD_RE.findall(value.casefold()))


def _source_ids(item) -> set[str]:
    return {
        str(ref.get("source_unit_id"))
        for ref in (item.source_refs_json or [])
        if isinstance(ref, dict) and ref.get("source_unit_id")
    }


def _match_score(item, group: list[tuple[object, object]]) -> float:
    item_title = _normalized_title(item.title)
    item_sources = _source_ids(item)
    best = 0.0
    for _, candidate in group:
        if item.source_fingerprint == candidate.source_fingerprint:
            return 1.0
        title_score = SequenceMatcher(None, item_title, _normalized_title(candidate.title)).ratio()
        candidate_sources = _source_ids(candidate)
        union = item_sources | candidate_sources
        source_score = len(item_sources & candidate_sources) / len(union) if union else 0.0
        same_object = bool(
            item.object_type
            and candidate.object_type
            and item.object_type.casefold() == candidate.object_type.casefold()
        )
        if source_score == 0 and not (title_score >= 0.88 and same_object):
            continue
        score = source_score * 0.68 + title_score * 0.27 + (0.05 if same_object else 0.0)
        best = max(best, score)
    return best


def _clean_ref(ref: dict) -> dict | None:
    source_unit_id = str(ref.get("source_unit_id") or "").strip()[:40]
    locator = str(ref.get("locator") or "").strip()[:500]
    excerpt = str(ref.get("excerpt") or "").strip()[:600]
    if not source_unit_id or not locator:
        return None
    return {
        "source_unit_id": source_unit_id,
        "locator": locator,
        "excerpt": excerpt,
    }


def evidence_text(source_refs: list[dict]) -> str | None:
    excerpts: list[str] = []
    seen: set[str] = set()
    for ref in source_refs:
        excerpt = str(ref.get("excerpt") or "").strip()
        key = excerpt.casefold()
        if not excerpt or key in seen:
            continue
        seen.add(key)
        excerpts.append(excerpt)
    return "\n\n".join(excerpts) or None


def build_model_comparison(registries: list[object]) -> list[ModelComparisonDraft]:
    """Build a review draft from one registry or reconcile multiple registries."""

    registry_count = len(registries)
    if registry_count < 1:
        raise ValueError("Выберите хотя бы один модельный реестр")
    entries: list[tuple[object, object]] = []
    for registry in sorted(registries, key=lambda item: (item.created_at, str(item.id))):
        for item in sorted(registry.items, key=lambda row: (row.sort_order, str(row.id))):
            entries.append((registry, item))

    groups: list[list[tuple[object, object]]] = []
    for registry, item in entries:
        best_index: int | None = None
        best_score = 0.0
        for index, group in enumerate(groups):
            if any(existing_registry.id == registry.id for existing_registry, _ in group):
                continue
            score = _match_score(item, group)
            if score >= 0.48 and score > best_score:
                best_index = index
                best_score = score
        if best_index is None:
            groups.append([(registry, item)])
        else:
            groups[best_index].append((registry, item))

    drafts: list[ModelComparisonDraft] = []
    for index, group in enumerate(groups, start=1):
        representative_registry, representative = max(
            group,
            key=lambda pair: (
                pair[1].confidence_percent if pair[1].confidence_percent is not None else -1,
                len(pair[1].source_refs_json or []),
                -pair[1].sort_order,
            ),
        )
        del representative_registry
        refs: list[dict] = []
        seen_refs: set[tuple[str, str, str]] = set()
        variants: list[dict] = []
        confidence_values: list[int] = []
        for registry, item in group:
            if item.confidence_percent is not None:
                confidence_values.append(int(item.confidence_percent))
            variants.append(
                {
                    "registry_id": str(registry.id),
                    "registry_item_id": str(item.id),
                    "provider_name": registry.provider_name,
                    "model_name": registry.model_name,
                    "title": item.title,
                    "object_type": item.object_type,
                    "work_type": item.work_type,
                    "confidence_percent": item.confidence_percent,
                }
            )
            for raw_ref in item.source_refs_json or []:
                if not isinstance(raw_ref, dict):
                    continue
                ref = _clean_ref(raw_ref)
                if ref is None:
                    continue
                key = (ref["source_unit_id"], ref["locator"], ref["excerpt"])
                if key in seen_refs:
                    continue
                seen_refs.add(key)
                refs.append(ref)
        refs.sort(key=lambda ref: (ref["source_unit_id"], ref["locator"], ref["excerpt"]))
        locators = list(dict.fromkeys(ref["locator"] for ref in refs))
        source_clause = "; ".join(locators)[:500] or representative.source_clause
        fingerprint_payload = {
            "items": sorted(str(item.id) for _, item in group),
            "sources": sorted(ref["source_unit_id"] for ref in refs),
            "title": _normalized_title(representative.title),
        }
        fingerprint = sha256(
            json.dumps(
                fingerprint_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        drafts.append(
            ModelComparisonDraft(
                title=representative.title,
                digital_product=representative.digital_product,
                work_type=representative.work_type,
                object_type=representative.object_type,
                source_clause=source_clause,
                notes=representative.notes,
                source_refs=refs,
                model_variants=variants,
                source_fingerprint=fingerprint,
                confidence_percent=(
                    round(sum(confidence_values) / len(confidence_values))
                    if confidence_values
                    else None
                ),
                agreement_count=len({str(registry.id) for registry, _ in group}),
                registry_count=registry_count,
                sort_order=index * 10,
            )
        )
    return drafts
