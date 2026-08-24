"""Bounded external-model atomization for canonical audit-tz source packets."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from hashlib import sha256
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.services.ai_provider import AIProviderError, generate_text


MAX_BATCH_SOURCE_UNITS = 32
MAX_BATCH_SOURCE_CHARS = 18_000
MAX_BATCH_ATOMS = 40
MAX_TOTAL_ATOMS = 400
MAX_SOURCE_REFS_PER_ATOM = 20
MAX_STORED_EXCERPT_CHARS = 600

_COVERAGE_DISPOSITIONS = {
    "ATOMIZED",
    "NON_REQUIREMENT",
    "DUPLICATE",
    "OUT_OF_SCOPE",
    "QUESTION",
    "BLOCKED",
}
_CONTRACT_CONTEXT_RE = re.compile(
    r"(?iu)(\b(?:договор|контракт)\w*"
    r"(?:\s+от\s+\d{1,2}[./-]\d{1,2}[./-]\d{2,4})?"
    r"\s*(?:№|N|номер)\s*[:\-]?\s*)"
)
_NUMBER_MARK_RE = re.compile(r"(?iu)(\b(?:№|N)\s*[:\-]?\s*)")
_IDENTIFIER_TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9._/\\\-]*")
_LONG_STRUCTURED_ID_RE = re.compile(r"(?<!\w)\d{2,}(?:\s*[-/]\s*\d{2,}){2,}(?!\w)")
_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9]+")
_GENERIC_ATOM_WORDS = {
    "в", "во", "для", "и", "из", "к", "на", "по", "при", "с", "со",
    "экран", "форма", "реестр", "таблица", "вкладка", "раздел", "функция",
}


class CanonicalAtomizationError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class _BatchAtom(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_id: str = Field(..., min_length=1, max_length=40, pattern=r"^A[0-9]{1,3}$")
    title: str = Field(..., min_length=3, max_length=500)
    object_type: str = Field(..., min_length=1, max_length=255)
    work_type: str | None = Field(None, max_length=255)
    notes: str | None = Field(None, max_length=2000)
    source_unit_ids: list[str] = Field(..., min_length=1, max_length=MAX_SOURCE_REFS_PER_ATOM)
    anchor_source_unit_id: str = Field(..., min_length=1, max_length=40)
    confidence: float | None = Field(None, ge=0, le=1)

    @field_validator("title", "object_type", "work_type", "notes", mode="before")
    @classmethod
    def clean_text(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @model_validator(mode="after")
    def validate_anchor(self):
        if self.anchor_source_unit_id not in self.source_unit_ids:
            raise ValueError("anchor_source_unit_id must be included in source_unit_ids")
        if len(set(self.source_unit_ids)) != len(self.source_unit_ids):
            raise ValueError("source_unit_ids must be unique")
        return self


class _BatchCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_unit_id: str = Field(..., min_length=1, max_length=40)
    disposition: Literal[
        "ATOMIZED",
        "NON_REQUIREMENT",
        "DUPLICATE",
        "OUT_OF_SCOPE",
        "QUESTION",
        "BLOCKED",
    ]
    reason: str = Field(..., min_length=2, max_length=500)


class _BatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    atoms: list[_BatchAtom] = Field(default_factory=list, max_length=MAX_BATCH_ATOMS)
    coverage: list[_BatchCoverage] = Field(..., min_length=1, max_length=MAX_BATCH_SOURCE_UNITS)
    warnings: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("warnings")
    @classmethod
    def clean_warnings(cls, values: list[str]) -> list[str]:
        result = [item.strip() for item in values if isinstance(item, str) and item.strip()]
        if any(len(item) > 500 for item in result):
            raise ValueError("warning is too long")
        return result


@dataclass(frozen=True)
class CanonicalSourceBatch:
    index: int
    units: list[dict]
    outbound_units: list[dict]
    payload_hash: str
    redaction_count: int


@dataclass(frozen=True)
class CanonicalBatchResult:
    batch_index: int
    payload_hash: str
    atoms: list[dict]
    coverage: list[dict]
    warnings: list[str]
    response_sha256: str
    redaction_count: int

    def as_storage(self) -> dict:
        return {
            "batch_index": self.batch_index,
            "payload_hash": self.payload_hash,
            "atoms": self.atoms,
            "coverage": self.coverage,
            "warnings": self.warnings,
            "response_sha256": self.response_sha256,
            "redaction_count": self.redaction_count,
        }


@dataclass(frozen=True)
class CanonicalDraft:
    title: str
    work_type: str | None
    object_type: str
    notes: str | None
    source_clause: str
    source_refs: list[dict]
    model_payload: dict
    source_fingerprint: str
    confidence_percent: int | None
    sort_order: int


@dataclass(frozen=True)
class CanonicalAtomizationResult:
    package: dict
    drafts: list[CanonicalDraft]
    coverage_summary: dict[str, int]
    warnings: list[str]
    source_manifest: list[dict]
    response_sha256: str
    redaction_count: int


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _model_json(raw: str) -> dict:
    value = raw.strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            value = "\n".join(lines[1:-1]).strip()
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as error:
        raise CanonicalAtomizationError(
            "invalid_model_json",
            "ИИ вернул ответ не в формате JSON",
            status_code=502,
        ) from error
    if not isinstance(payload, dict):
        raise CanonicalAtomizationError(
            "invalid_model_schema",
            "ИИ вернул некорректную структуру атомов",
            status_code=502,
        )
    return payload


def _marked_identifier_matches(text: str) -> list[tuple[str, int, int]]:
    """Return identifier text and span after a contract/number marker."""

    matches: list[tuple[str, int, int]] = []
    matched_spans: set[tuple[int, int]] = set()
    marker_matches = list(_CONTRACT_CONTEXT_RE.finditer(text))
    marker_spans = {(match.start(), match.end()) for match in marker_matches}
    marker_matches.extend(
        match for match in _NUMBER_MARK_RE.finditer(text)
        if (match.start(), match.end()) not in marker_spans
    )
    for marker in marker_matches:
        tail = text[marker.end(): marker.end() + 180]
        tokens: list[re.Match[str]] = []
        for token in _IDENTIFIER_TOKEN_RE.finditer(tail):
            if tokens and tail[tokens[-1].end():token.start()].strip():
                break
            value = token.group(0)
            letters = "".join(char for char in value if char.isalpha())
            if not any(char.isdigit() for char in value) and not (letters and letters.isupper()):
                break
            tokens.append(token)
            if len(tokens) >= 5:
                break
        if not tokens:
            continue
        value = tail[tokens[0].start():tokens[-1].end()].strip()
        if len(value) < 2 or not any(char.isdigit() for char in value):
            continue
        start = marker.end() + tokens[0].start()
        end = marker.end() + tokens[-1].end()
        if (start, end) in matched_spans:
            continue
        matched_spans.add((start, end))
        matches.append((value, start, end))
    return sorted(matches, key=lambda item: item[1])


def _identifier_pattern(identifier: str) -> re.Pattern[str]:
    chunks = re.split(r"(\s+)", identifier.strip())
    body = "".join(r"\s+" if chunk.isspace() else re.escape(chunk) for chunk in chunks)
    return re.compile(rf"(?<!\w){body}(?!\w)", re.IGNORECASE)


def discover_contract_requisites(source_units: list[dict]) -> set[str]:
    """Discover likely document/contract identifiers before any outbound batch is built."""

    identifiers: set[str] = set()
    for unit in source_units:
        text = str(unit.get("text") or "")
        identifiers.update(value for value, _, _ in _marked_identifier_matches(text))
        identifiers.update(match.group(0).strip() for match in _LONG_STRUCTURED_ID_RE.finditer(text))
    return {item for item in identifiers if len(item) >= 2}


def redact_contract_requisites(
    text: str,
    known_identifiers: set[str] | None = None,
) -> tuple[str, int]:
    """Mask likely contract identifiers without requiring a business number from the user."""

    redactions = 0
    contract_marker_present = bool(_CONTRACT_CONTEXT_RE.search(text))
    sanitized = text
    for identifier in sorted(known_identifiers or set(), key=len, reverse=True):
        sanitized, count = _identifier_pattern(identifier).subn("[РЕКВИЗИТ-СКРЫТ]", sanitized)
        redactions += count
    for _, start, end in reversed(_marked_identifier_matches(sanitized)):
        sanitized = sanitized[:start] + "[РЕКВИЗИТ-СКРЫТ]" + sanitized[end:]
        redactions += 1
    sanitized, structured = _LONG_STRUCTURED_ID_RE.subn("[РЕКВИЗИТ-СКРЫТ]", sanitized)
    redactions += structured
    if _marked_identifier_matches(sanitized) or _LONG_STRUCTURED_ID_RE.search(sanitized):
        raise CanonicalAtomizationError(
            "privacy_redaction_incomplete",
            "Реквизиты документа не удалось надежно обезличить; передача ИИ заблокирована",
            status_code=409,
        )
    if contract_marker_present and redactions == 0:
        raise CanonicalAtomizationError(
            "privacy_requisite_unrecognized",
            "После маркера договора найден неизвестный формат реквизита; передача ИИ заблокирована",
            status_code=409,
        )
    return sanitized, redactions


def _source_units(prompt_packet: dict) -> list[dict]:
    units = prompt_packet.get("source_units")
    if not isinstance(units, list) or not units:
        raise CanonicalAtomizationError(
            "canonical_prompt_invalid",
            "Canonical runtime не вернул исходные фрагменты",
            status_code=500,
        )
    result: list[dict] = []
    seen: set[str] = set()
    for item in units:
        if not isinstance(item, dict):
            raise CanonicalAtomizationError("canonical_prompt_invalid", "Фрагмент ТЗ поврежден", status_code=500)
        unit_id = item.get("source_unit_id")
        text = item.get("text")
        locator = item.get("source_locator")
        if (
            not isinstance(unit_id, str)
            or not unit_id
            or unit_id in seen
            or not isinstance(text, str)
            or not text.strip()
            or not isinstance(locator, str)
            or not locator
        ):
            raise CanonicalAtomizationError("canonical_prompt_invalid", "Фрагмент ТЗ поврежден", status_code=500)
        seen.add(unit_id)
        result.append(item)
    return result


def build_source_batches(prompt_packet: dict) -> list[CanonicalSourceBatch]:
    source_units = _source_units(prompt_packet)
    known_identifiers = discover_contract_requisites(source_units)
    batches: list[list[dict]] = []
    current: list[dict] = []
    current_chars = 0
    for unit in source_units:
        text_length = len(str(unit["text"]))
        if current and (
            len(current) >= MAX_BATCH_SOURCE_UNITS
            or current_chars + text_length > MAX_BATCH_SOURCE_CHARS
        ):
            batches.append(current)
            current = []
            current_chars = 0
        current.append(unit)
        current_chars += text_length
    if current:
        batches.append(current)

    result: list[CanonicalSourceBatch] = []
    for index, units in enumerate(batches, start=1):
        outbound_units: list[dict] = []
        redaction_count = 0
        for unit in units:
            sanitized, count = redact_contract_requisites(
                str(unit["text"]),
                known_identifiers,
            )
            redaction_count += count
            outbound_units.append(
                {
                    "source_unit_id": unit["source_unit_id"],
                    "text": sanitized,
                }
            )
        payload_hash = sha256(_canonical_json(outbound_units).encode("utf-8")).hexdigest()
        result.append(
            CanonicalSourceBatch(
                index=index,
                units=units,
                outbound_units=outbound_units,
                payload_hash=payload_hash,
                redaction_count=redaction_count,
            )
        )
    return result


_CORRECTION_GUIDANCE = {
    "invalid_model_json": "Верни один валидный JSON-объект без Markdown и пояснений.",
    "invalid_model_schema": "Строго соблюдай переданную JSON-схему, обязательные поля и допустимые значения.",
    "coverage_gap": "Добавь ровно одно coverage-решение для каждого переданного source_unit_id.",
    "duplicate_coverage": "Каждый source_unit_id должен встречаться в coverage ровно один раз.",
    "coverage_atom_mismatch": "Каждый anchor_source_unit_id атома должен иметь disposition ATOMIZED.",
    "atomized_unit_not_referenced": "Каждый фрагмент с ATOMIZED должен быть anchor_source_unit_id хотя бы одного атома.",
    "unknown_source_reference": "Используй только source_unit_id из текущего пакета.",
    "duplicate_model_atom": "Используй уникальные local_id и не возвращай повторяющиеся атомы.",
}


def build_batch_messages(
    batch: CanonicalSourceBatch,
    total_batches: int,
    *,
    correction_code: str | None = None,
) -> list[dict[str, str]]:
    system = """Ты выполняешь техническую атомизацию ТЗ цифрового продукта.
Атом — один самостоятельно демонстрируемый и проверяемый элемент продукта: экран, вкладка, форма, реестр, таблица, фильтр, показатель, отчет, действие пользователя, уведомление, интеграция или отдельное наблюдаемое поведение.
Не превращай заголовки, определения, реквизиты, общие организационные фразы и каждое предложение в отдельный атом. Объединяй неразделимые детали одного элемента и разделяй только то, что можно проверить независимо.
Не придумывай функциональность. Каждый атом должен иметь короткое однозначное название, тип объекта и ссылки только на переданные source_unit_id.
Для атома выбери один anchor_source_unit_id. Дополнительные фрагменты можно указать в source_unit_ids как основание. Только anchor получает coverage ATOMIZED; поясняющие фрагменты обычно получают DUPLICATE или NON_REQUIREMENT с понятной причиной.
Каждый переданный фрагмент обязан получить ровно одно coverage-решение. Верни только JSON без Markdown."""
    payload = {
        "protocol": "dpms-canonical-audit-atomization-v1",
        "batch": {"index": batch.index, "total": total_batches},
        "source_units": batch.outbound_units,
        "output_schema": {
            "atoms": [
                {
                    "local_id": "A1",
                    "title": "Проверяемый элемент цифрового продукта",
                    "object_type": "Экран|Вкладка|Форма|Реестр|Таблица|Фильтр|Показатель|Отчет|Действие|Уведомление|Интеграция|Поведение|Другое",
                    "work_type": "string|null",
                    "notes": "string|null",
                    "source_unit_ids": ["U000001"],
                    "anchor_source_unit_id": "U000001",
                    "confidence": "number 0..1|null",
                }
            ],
            "coverage": [
                {
                    "source_unit_id": "U000001",
                    "disposition": "ATOMIZED|NON_REQUIREMENT|DUPLICATE|OUT_OF_SCOPE|QUESTION|BLOCKED",
                    "reason": "string",
                }
            ],
            "warnings": ["string"],
        },
    }
    guidance = _CORRECTION_GUIDANCE.get(correction_code or "")
    if guidance:
        payload["correction"] = {
            "previous_response_rejected": correction_code,
            "required_fix": guidance,
        }
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": _canonical_json(payload)},
    ]


def validate_batch_result(
    raw_or_payload: str | dict,
    batch: CanonicalSourceBatch,
    *,
    response_sha256: str | None = None,
) -> CanonicalBatchResult:
    payload = _model_json(raw_or_payload) if isinstance(raw_or_payload, str) else raw_or_payload
    try:
        parsed = _BatchResult.model_validate(payload)
    except ValidationError as error:
        raise CanonicalAtomizationError(
            "invalid_model_schema",
            "ИИ вернул неполный или некорректный пакет атомов",
            status_code=502,
        ) from error
    known_units = {str(item["source_unit_id"]) for item in batch.units}
    coverage_by_unit: dict[str, _BatchCoverage] = {}
    for item in parsed.coverage:
        if item.source_unit_id not in known_units:
            raise CanonicalAtomizationError("unknown_source_reference", "ИИ сослался на неизвестный фрагмент", status_code=502)
        if item.source_unit_id in coverage_by_unit:
            raise CanonicalAtomizationError("duplicate_coverage", "ИИ дважды классифицировал фрагмент", status_code=502)
        coverage_by_unit[item.source_unit_id] = item
    if set(coverage_by_unit) != known_units:
        raise CanonicalAtomizationError(
            "coverage_gap",
            "ИИ пропустил часть ТЗ; неполный черновик не сохранен",
            status_code=502,
        )

    local_ids: set[str] = set()
    anchored_units: set[str] = set()
    fingerprints: set[str] = set()
    atoms: list[dict] = []
    for atom in parsed.atoms:
        if atom.local_id in local_ids:
            raise CanonicalAtomizationError("duplicate_model_atom", "ИИ повторил идентификатор атома", status_code=502)
        local_ids.add(atom.local_id)
        if any(unit_id not in known_units for unit_id in atom.source_unit_ids):
            raise CanonicalAtomizationError("unknown_source_reference", "ИИ сослался на неизвестный фрагмент", status_code=502)
        if coverage_by_unit[atom.anchor_source_unit_id].disposition != "ATOMIZED":
            raise CanonicalAtomizationError(
                "coverage_atom_mismatch",
                "Опорный фрагмент атома не отмечен как атомизированный",
                status_code=502,
            )
        anchored_units.add(atom.anchor_source_unit_id)
        fingerprint = sha256(
            _canonical_json(
                {
                    "title": atom.title.casefold(),
                    "source_unit_ids": sorted(atom.source_unit_ids),
                }
            ).encode("utf-8")
        ).hexdigest()
        if fingerprint in fingerprints:
            raise CanonicalAtomizationError("duplicate_model_atom", "ИИ вернул одинаковые атомы", status_code=502)
        fingerprints.add(fingerprint)
        atoms.append(atom.model_dump(mode="json"))
    atomized_units = {
        unit_id
        for unit_id, coverage in coverage_by_unit.items()
        if coverage.disposition == "ATOMIZED"
    }
    if atomized_units != anchored_units:
        raise CanonicalAtomizationError(
            "atomized_unit_not_referenced",
            "Не каждый атомизированный фрагмент связан с атомом",
            status_code=502,
        )
    raw_hash = response_sha256 or sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    return CanonicalBatchResult(
        batch_index=batch.index,
        payload_hash=batch.payload_hash,
        atoms=atoms,
        coverage=[item.model_dump(mode="json") for item in parsed.coverage],
        warnings=parsed.warnings,
        response_sha256=raw_hash,
        redaction_count=batch.redaction_count,
    )


async def generate_batch_result(
    provider,
    batch: CanonicalSourceBatch,
    total_batches: int,
    *,
    correction_code: str | None = None,
) -> CanonicalBatchResult:
    messages = build_batch_messages(batch, total_batches, correction_code=correction_code)
    try:
        raw = await generate_text(provider, messages, max_tokens=4096, temperature=0)
    except AIProviderError:
        raise
    return validate_batch_result(
        raw,
        batch,
        response_sha256=sha256(raw.encode("utf-8")).hexdigest(),
    )


def restore_batch_result(payload: dict, batch: CanonicalSourceBatch) -> CanonicalBatchResult:
    if (
        not isinstance(payload, dict)
        or payload.get("batch_index") != batch.index
        or payload.get("payload_hash") != batch.payload_hash
    ):
        raise CanonicalAtomizationError(
            "atomization_checkpoint_invalid",
            "Сохраненный пакет атомизации не соответствует исходному документу",
            status_code=500,
        )
    result = validate_batch_result(
        {
            "atoms": payload.get("atoms"),
            "coverage": payload.get("coverage"),
            "warnings": payload.get("warnings", []),
        },
        batch,
        response_sha256=str(payload.get("response_sha256") or ""),
    )
    if not re.fullmatch(r"[0-9a-f]{64}", result.response_sha256):
        raise CanonicalAtomizationError("atomization_checkpoint_invalid", "Hash ответа ИИ поврежден", status_code=500)
    return result


def _atom_terms(title: str) -> set[str]:
    return {
        token.casefold()
        for token in _WORD_RE.findall(title)
        if len(token) > 1 and token.casefold() not in _GENERIC_ATOM_WORDS
    }


def _same_semantic_atom(left: dict, right: dict) -> bool:
    left_title = " ".join(_WORD_RE.findall(str(left["title"]).casefold()))
    right_title = " ".join(_WORD_RE.findall(str(right["title"]).casefold()))
    if left_title == right_title:
        return True
    left_terms = _atom_terms(left_title)
    right_terms = _atom_terms(right_title)
    if not left_terms or not right_terms:
        return False
    common = len(left_terms & right_terms)
    containment = common / min(len(left_terms), len(right_terms))
    jaccard = common / len(left_terms | right_terms)
    sequence = SequenceMatcher(None, left_title, right_title).ratio()
    same_type = str(left.get("object_type") or "").casefold() == str(
        right.get("object_type") or ""
    ).casefold()
    return bool(
        (containment == 1 and (same_type or sequence >= 0.72))
        or (same_type and jaccard >= 0.8 and sequence >= 0.72)
        or (jaccard >= 0.9 and sequence >= 0.82)
    )


def consolidate_model_atoms(model_atoms: list[dict]) -> tuple[list[dict], dict[str, str]]:
    """Merge repeated semantic candidates produced by independent source batches."""

    consolidated: list[dict] = []
    duplicate_anchors: dict[str, str] = {}
    for raw_atom in model_atoms:
        candidate = {
            **raw_atom,
            "source_unit_ids": list(dict.fromkeys(str(item) for item in raw_atom["source_unit_ids"])),
        }
        target = next((item for item in consolidated if _same_semantic_atom(item, candidate)), None)
        if target is None:
            consolidated.append(candidate)
            continue
        combined_sources = list(dict.fromkeys(target["source_unit_ids"] + candidate["source_unit_ids"]))
        if len(combined_sources) > MAX_SOURCE_REFS_PER_ATOM:
            consolidated.append(candidate)
            continue
        duplicate_anchors[str(candidate["anchor_source_unit_id"])] = str(target["title"])
        target["source_unit_ids"] = combined_sources
        if len(str(candidate["title"])) > len(str(target["title"])):
            target["title"] = candidate["title"]
        if not target.get("work_type") and candidate.get("work_type"):
            target["work_type"] = candidate["work_type"]
        if not target.get("notes") and candidate.get("notes"):
            target["notes"] = candidate["notes"]
        confidences = [
            float(value)
            for value in (target.get("confidence"), candidate.get("confidence"))
            if value is not None
        ]
        target["confidence"] = max(confidences) if confidences else None
    return consolidated, duplicate_anchors


def assemble_atomization_result(
    prompt_packet: dict,
    batch_results: list[CanonicalBatchResult],
    *,
    model_name: str,
) -> CanonicalAtomizationResult:
    units = _source_units(prompt_packet)
    unit_by_id = {str(item["source_unit_id"]): item for item in units}
    expected_batches = build_source_batches(prompt_packet)
    if len(batch_results) != len(expected_batches):
        raise CanonicalAtomizationError("coverage_gap", "Не все пакеты ТЗ обработаны", status_code=500)
    result_by_index = {item.batch_index: item for item in batch_results}
    ordered_results: list[CanonicalBatchResult] = []
    for batch in expected_batches:
        result = result_by_index.get(batch.index)
        if result is None or result.payload_hash != batch.payload_hash:
            raise CanonicalAtomizationError("coverage_gap", "Не все пакеты ТЗ обработаны", status_code=500)
        ordered_results.append(result)

    canonical_atoms: list[dict] = []
    drafts: list[CanonicalDraft] = []
    coverage: list[dict] = []
    warnings: list[str] = []
    redaction_count = 0
    raw_model_atoms: list[dict] = []
    for batch_result in ordered_results:
        coverage.extend(batch_result.coverage)
        warnings.extend(batch_result.warnings)
        redaction_count += batch_result.redaction_count
        raw_model_atoms.extend(batch_result.atoms)

    model_atoms, duplicate_anchors = consolidate_model_atoms(raw_model_atoms)
    if len(model_atoms) > MAX_TOTAL_ATOMS:
        raise CanonicalAtomizationError(
            "too_many_atoms",
            "После межпакетной консолидации осталось больше 400 атомов; требуется уточнение методики",
            status_code=422,
        )
    surviving_anchors = {
        str(item["anchor_source_unit_id"])
        for item in model_atoms
    }
    reclassified_duplicate_count = 0
    if duplicate_anchors:
        for item in coverage:
            target_title = duplicate_anchors.get(str(item["source_unit_id"]))
            if (
                target_title
                and str(item["source_unit_id"]) not in surviving_anchors
                and item["disposition"] == "ATOMIZED"
            ):
                item["disposition"] = "DUPLICATE"
                item["reason"] = f"Объединено с межпакетным атомом: {target_title}"[:500]
                reclassified_duplicate_count += 1
    if reclassified_duplicate_count:
        warnings.append(
            "Межпакетная консолидация объединила "
            f"{reclassified_duplicate_count} повторяющихся атомов"
        )
    coverage_summary = {item: 0 for item in sorted(_COVERAGE_DISPOSITIONS)}
    for item in coverage:
        coverage_summary[str(item["disposition"])] += 1

    for atom_number, model_atom in enumerate(model_atoms, start=1):
        atom_id = f"P-{atom_number:04d}"
        anchor = unit_by_id[str(model_atom["anchor_source_unit_id"])]
        source_ids = [str(item) for item in model_atom["source_unit_ids"]]
        source_refs = [
            {
                "source_unit_id": unit_id,
                "locator": str(unit_by_id[unit_id]["source_locator"])[:500],
                "excerpt": str(unit_by_id[unit_id]["text"])[:MAX_STORED_EXCERPT_CHARS],
            }
            for unit_id in source_ids
        ]
        canonical_atom = {
            "atom_id": atom_id,
            "run_id": anchor["run_id"],
            "raw_contract_id": anchor["raw_contract_id"],
            "canonical_contract_id": anchor["canonical_contract_id"],
            "match_status": anchor["match_status"],
            "source_sha256": anchor["source_sha256"],
            "source_unit_id": anchor["source_unit_id"],
            "source_locator": anchor["source_locator"],
            "source_text_hash": anchor["text_hash"],
            "lane": "primary",
            "extractor_version": anchor["extractor_version"],
            "schema_version": anchor["schema_version"],
            "gate_bundle_hash": anchor["gate_bundle_hash"],
            "atom_text": model_atom["title"],
            "object_type": model_atom["object_type"],
            "work_type": model_atom.get("work_type"),
            "notes": model_atom.get("notes"),
            "confidence": model_atom.get("confidence"),
            "source_unit_ids": source_ids,
        }
        canonical_atoms.append(canonical_atom)
        source_fingerprint = sha256(
            _canonical_json(
                {
                    "title": str(model_atom["title"]).casefold(),
                    "source_unit_ids": sorted(source_ids),
                }
            ).encode("utf-8")
        ).hexdigest()
        drafts.append(
            CanonicalDraft(
                title=str(model_atom["title"]),
                work_type=model_atom.get("work_type"),
                object_type=str(model_atom["object_type"]),
                notes=model_atom.get("notes"),
                source_clause="; ".join(ref["locator"] for ref in source_refs)[:500],
                source_refs=source_refs,
                model_payload={
                    "atom_id": atom_id,
                    "source_unit_ids": source_ids,
                    "confidence": model_atom.get("confidence"),
                },
                source_fingerprint=source_fingerprint,
                confidence_percent=(
                    round(float(model_atom["confidence"]) * 100)
                    if model_atom.get("confidence") is not None
                    else None
                ),
                sort_order=len(drafts) * 10 + 10,
            )
        )

    if not canonical_atoms:
        raise CanonicalAtomizationError(
            "no_atoms_found",
            "Модель не выделила ни одного проверяемого элемента; требуется повторная проверка методики",
            status_code=422,
        )
    package = {
        "gate_bundle_hash": prompt_packet["gate_bundle_hash"],
        "source_sha256": prompt_packet["source_sha256"],
        "prompt_version": "1.0",
        "prompt_packet_hash": prompt_packet["prompt_packet_hash"],
        "producer": {
            "lane": "primary",
            "model": model_name,
            "prompt_version": "1.0",
        },
        "atoms": canonical_atoms,
        "coverage": coverage,
    }
    source_manifest = [
        {
            "source_unit_id": unit["source_unit_id"],
            "locator": unit["source_locator"],
            "text_sha256": unit["text_hash"],
            "char_count": len(str(unit["text"])),
        }
        for unit in units
    ]
    response_sha256 = sha256(
        _canonical_json([item.response_sha256 for item in ordered_results]).encode("utf-8")
    ).hexdigest()
    return CanonicalAtomizationResult(
        package=package,
        drafts=drafts,
        coverage_summary=coverage_summary,
        warnings=list(dict.fromkeys(warnings))[:50],
        source_manifest=source_manifest,
        response_sha256=response_sha256,
        redaction_count=redaction_count,
    )
