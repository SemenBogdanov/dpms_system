"""Deterministic preparation and reconciliation of audit atom proposals."""

from __future__ import annotations

from dataclasses import dataclass
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
    # Unit numbers are local to an extractor; different methods may reuse U000001.
    return {
        json.dumps(
            [str(ref.get("locator") or ""), str(ref.get("excerpt") or "")],
            ensure_ascii=False,
        )
        for ref in (item.source_refs_json or [])
        if isinstance(ref, dict) and ref.get("locator") and ref.get("excerpt")
    }


def _comparison_signature(item) -> tuple | None:
    item_sources = _source_ids(item)
    if not item_sources:
        return None
    # Preserve case-sensitive identifiers, product scope and verification conditions.
    fields = ("title", "digital_product", "object_type", "work_type", "notes", "source_clause")
    return (
        *(" ".join(str(getattr(item, field, None) or "").split()) for field in fields),
        tuple(sorted(item_sources)),
    )


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
    group_indexes: dict[tuple, list[int]] = {}
    group_registries: list[set[object]] = []
    for registry, item in entries:
        signature = _comparison_signature(item)
        best_index = next((index for index in group_indexes.get(signature, [])
                           if registry.id not in group_registries[index]), None)
        if best_index is None:
            best_index = len(groups)
            groups.append([(registry, item)])
            group_registries.append({registry.id})
            if signature is not None:
                group_indexes.setdefault(signature, []).append(best_index)
        else:
            groups[best_index].append((registry, item))
            group_registries[best_index].add(registry.id)

    drafts: list[ModelComparisonDraft] = []
    for index, group in enumerate(groups, start=1):
        _, representative = group[0]
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
                confidence_percent=confidence_values[0] if len(group) == 1 and confidence_values else None,
                agreement_count=len({str(registry.id) for registry, _ in group}),
                registry_count=registry_count,
                sort_order=index * 10,
            )
        )
    return drafts
