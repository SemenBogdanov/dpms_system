"""Data-only DOCX/PDF preflight and packet adapter for the durable audit worker."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re

from fastapi import HTTPException

from app.services.audit_ai_atomization import (
    AuditAIAtomizationError,
    MAX_SOURCE_BYTES,
    _extract_docx_blocks,
    _extract_pdf_blocks,
)
from app.services.audit_skill_package import parse_audit_skill_upload
from app.services.audit_tz_atomization import (
    MAX_METHODOLOGY_BYTES,
    CanonicalAtomizationError,
    assemble_atomization_result,
    build_source_batches,
    restore_batch_result,
)


NATIVE_PROTOCOL = "dpms-declarative-runtime-v1"
DECLARATIVE_FORMATS = frozenset({"declarative_archive", "declarative_json"})
MAX_NATIVE_SOURCE_UNITS = 10_000
MAX_NATIVE_SOURCE_CHARS = 4_000_000


def _digest(value: object) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def is_declarative_skill(version) -> bool:
    return getattr(version, "package_format", None) in DECLARATIVE_FORMATS


def build_methodology_snapshot(version) -> dict:
    """Import stores SKILL.md plus all references in immutable instructions_text."""
    instructions = getattr(version, "instructions_text", "")
    rules = getattr(version, "rules_json", [])
    if (
        not isinstance(instructions, str) or not instructions.strip()
        or not isinstance(rules, list) or any(not isinstance(rule, str) for rule in rules)
    ):
        raise CanonicalAtomizationError("methodology_invalid", "Выбранная методика не содержит корректных инструкций")
    if sum(len(value.encode("utf-8")) for value in [instructions, *rules]) > MAX_METHODOLOGY_BYTES:
        raise CanonicalAtomizationError("methodology_too_large", "Текст методики превышает 128 КиБ", status_code=413)
    if version.package_format == "declarative_archive":
        blob = bytes(getattr(version, "package_blob", None) or b"")
        if not blob or sha256(blob).hexdigest() != version.content_sha256:
            raise CanonicalAtomizationError("skill_integrity_failed", "Контрольная сумма сохранённого архива skill изменилась", status_code=409)
        # Reuse the import validator; never extract, import, or execute package files.
        try:
            parsed = parse_audit_skill_upload("methodology.skill", blob)
        except HTTPException as error:
            raise CanonicalAtomizationError("skill_integrity_failed", "Сохранённый декларативный архив не прошёл проверку", status_code=409) from error
        if parsed.package_format != "declarative_archive" or parsed.instructions != instructions or parsed.rules != rules:
            raise CanonicalAtomizationError("methodology_changed", "Импортированная методика не соответствует сохранённому архиву", status_code=409)
    content = {"instructions": instructions, "rules": list(rules)}
    return {
        **content,
        "skill_sha256": version.content_sha256,
        "package_format": version.package_format,
        "snapshot_sha256": _digest(content),
    }


@dataclass(frozen=True)
class NativePreflight:
    identity_report: dict
    gated_evidence_bundle: dict
    source_units: dict
    prompt_packet: dict


def build_native_preflight(
    data: bytes,
    *,
    run_id: str,
    source_sha256: str,
    binding_id: str,
    methodology: dict,
    source_kind: str = "docx",
) -> NativePreflight:
    if not re.fullmatch(r"[0-9a-f]{64}", source_sha256) or sha256(data).hexdigest() != source_sha256:
        raise CanonicalAtomizationError("document_hash_changed", "Контрольная сумма зафиксированного документа изменилась", status_code=409)
    if not data or len(data) > MAX_SOURCE_BYTES:
        raise CanonicalAtomizationError("document_size_invalid", "Документ пустой или превышает допустимый размер подготовки", status_code=413)
    if source_kind not in {"docx", "pdf"}:
        raise CanonicalAtomizationError("unsupported_document_type", "Декларативная методика поддерживает DOCX и текстовые PDF")
    try:
        blocks = _extract_pdf_blocks(data) if source_kind == "pdf" else _extract_docx_blocks(data)
    except AuditAIAtomizationError as error:
        raise CanonicalAtomizationError(error.code, error.message, status_code=error.status_code) from error
    if not blocks:
        raise CanonicalAtomizationError("document_text_empty", "В документе не найден извлекаемый текст; распознавание сканов (OCR) не выполняется")
    if len(blocks) > MAX_NATIVE_SOURCE_UNITS or sum(len(text) for _, text in blocks) > MAX_NATIVE_SOURCE_CHARS:
        raise CanonicalAtomizationError("document_text_too_large", "Объём текста документа превышает допустимый размер обработки", status_code=413)
    bundle = {
        "protocol": NATIVE_PROTOCOL,
        "run_id": str(run_id),
        "source_sha256": source_sha256,
        "source_binding": "document_hash",
        "source_kind": source_kind,
        "methodology": methodology,
        "source_text_hashes": [sha256(text.encode("utf-8")).hexdigest() for _, text in blocks],
    }
    bundle_hash = _digest(bundle)
    units = [
        {
            "source_unit_id": f"U{index:06d}", "source_locator": locator,
            "source_kind": "page_text" if source_kind == "pdf" else "paragraph", "text": text,
            "text_hash": sha256(text.encode("utf-8")).hexdigest(),
            "source_sha256": source_sha256, "run_id": str(run_id),
            "raw_contract_id": binding_id, "canonical_contract_id": binding_id,
            "match_status": "SAME_TARGET", "block_id": f"B{index}", "lane": "source",
            "extractor_version": NATIVE_PROTOCOL, "schema_version": "1.0",
            "gate_bundle_hash": bundle_hash, "order": index,
        }
        for index, (locator, text) in enumerate(blocks, start=1)
    ]
    packet = {
        "protocol": NATIVE_PROTOCOL, "run_id": str(run_id),
        "source_sha256": source_sha256, "source_binding": "document_hash",
        "source_kind": source_kind,
        "gate_bundle_hash": bundle_hash, "methodology": methodology, "source_units": units,
    }
    packet["prompt_packet_hash"] = _digest(packet)
    report = {
        "decision": "PASS", "comparison_eligible": True,
        "source": {"kind": source_kind, "unit_count": len(units), "external_relationship_count": 0},
        "warnings": ["Подготовка охватывает извлечённый текст документа, но не изображения, не выполняет OCR и не доказывает смысловую полноту."],
        "protocol": NATIVE_PROTOCOL,
    }
    return NativePreflight(report, {**bundle, "gate_bundle_hash": bundle_hash}, {"source_units": units}, packet)


def validate_native_prompt(
    packet: dict, *, run_id: str, source_sha256: str, methodology: dict, source_kind: str = "docx",
) -> None:
    expected_hash = _digest({key: value for key, value in packet.items() if key != "prompt_packet_hash"})
    if (
        packet.get("protocol") != NATIVE_PROTOCOL or packet.get("run_id") != str(run_id)
        or packet.get("source_binding") != "document_hash" or packet.get("source_sha256") != source_sha256
        or packet.get("source_kind", "docx") != source_kind
        or packet.get("methodology") != methodology or packet.get("prompt_packet_hash") != expected_hash
    ):
        raise CanonicalAtomizationError("runtime_context_changed", "Сохранённый снимок запроса атомизации изменился", status_code=409)
    for batch in build_source_batches(packet):
        for unit in batch.units:
            if (
                unit.get("run_id") != str(run_id) or unit.get("source_sha256") != source_sha256
                or unit.get("gate_bundle_hash") != packet.get("gate_bundle_hash")
                or unit.get("text_hash") != sha256(unit["text"].encode("utf-8")).hexdigest()
            ):
                raise CanonicalAtomizationError("runtime_context_changed", "Сохранённый снимок исходных фрагментов изменился", status_code=409)


def validate_native_atomization(packet: dict, batch_results: list, *, model_name: str):
    batches = build_source_batches(packet)
    if len(batch_results) != len(batches) or len({item.batch_index for item in batch_results}) != len(batches):
        raise CanonicalAtomizationError("coverage_gap", "Результат атомизации охватывает не все пакеты документа")
    by_index = {item.batch_index: item for item in batch_results}
    validated = []
    for batch in batches:
        if batch.index not in by_index:
            raise CanonicalAtomizationError("coverage_gap", "В результате атомизации отсутствует пакет документа")
        validated.append(restore_batch_result(by_index[batch.index].as_storage(), batch))
    return assemble_atomization_result(packet, validated, model_name=model_name, consolidate=False)
