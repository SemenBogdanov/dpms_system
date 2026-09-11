"""Native packets and durable model-mock tests; no external model or database."""

from contextlib import asynccontextmanager
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from xml.sax.saxutils import escape
from zipfile import ZipFile

from fastapi import HTTPException
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.config import settings
from app.models.ai_provider import AIProviderConfig, AuditAtomizationSkill, AuditAtomizationSkillVersion
from app.models.audit import (
    AuditAIAtomizationAttempt, AuditAIModelRegistry, AuditAIModelRegistryItem,
    AuditCase, AuditDocument, AuditTeamMember,
)
from app.models.audit_runtime import AuditTZArtifact, AuditTZRun, AuditTZRuntimeJob
from app.models.user import User, UserRole
from app.services.audit_declarative_runtime import (
    NATIVE_PROTOCOL, build_methodology_snapshot, build_native_preflight,
    validate_native_atomization, validate_native_prompt,
)
from app.services.audit_skill_package import parse_audit_skill_upload
from app.services.audit_tz_atomization import (
    CanonicalAtomizationError, build_batch_messages, build_source_batches,
    restore_batch_result, validate_batch_result,
)
from app.services.audit_tz_runtime import (
    _generate_batch_with_retry, _registry_autoappend_blocker,
    AuditTZRuntimeError, _copy_source, document_binding_id, process_atomization, process_preflight,
)
from tests.test_audit_tz_atomization import prompt_packet as legacy_prompt_packet, source_unit


def docx(paragraphs, *, external=False):
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        body = "".join(f"<w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p>" for text in paragraphs)
        archive.writestr("word/document.xml", (
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body>{body}</w:body></w:document>"
        ))
        if external:
            archive.writestr("word/_rels/document.xml.rels", '<Relationships><Relationship TargetMode="External" /></Relationships>')
    return output.getvalue()


def pdf(pages, *, encrypted=False):
    writer = PdfWriter()
    for text in pages:
        page = writer.add_blank_page(width=612, height=792)
        if text is None:
            continue
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        })
        stream = DecodedStreamObject()
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream.set_data(f"BT /F1 12 Tf 40 740 Td ({escaped}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt("synthetic-test-password")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def archive_version():
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("arbitrary-method/SKILL.md", (
            "---\nname: arbitrary-method\ndescription: Synthetic methodology\n---\n"
            "Keep every independently testable requirement. [Details](references/detail.md)"
        ))
        archive.writestr("arbitrary-method/references/detail.md", "REFERENCE-ONLY: distinguish opposite conditions.")
    blob = output.getvalue()
    parsed = parse_audit_skill_upload("arbitrary.skill", blob)
    return SimpleNamespace(
        id=uuid4(), skill_id=uuid4(), package_format=parsed.package_format,
        package_blob=blob, instructions_text=parsed.instructions, rules_json=parsed.rules,
        content_sha256=parsed.content_sha256, is_active=True, runtime_status="ready",
    )


def json_version(instructions="Keep independently testable requirements.", rules=None):
    return SimpleNamespace(
        id=uuid4(), skill_id=uuid4(), package_format="declarative_json", package_blob=None,
        content_sha256="b" * 64, instructions_text=instructions, rules_json=rules or [],
        is_active=True, runtime_status="ready",
    )


def packet_for(paragraphs=None, version=None):
    data = docx(paragraphs or ["Show the status field."])
    digest = sha256(data).hexdigest()
    return build_native_preflight(
        data, run_id="native-test", source_sha256=digest, binding_id=document_binding_id(digest),
        methodology=build_methodology_snapshot(version or json_version()),
    ).prompt_packet


def model_payload(units):
    return {
        "atoms": [
            {"local_id": f"A{index}", "title": "Status field in its own context", "object_type": "Field",
             "notes": "Условия проверки: открыть соответствующий экран; Ожидаемый результат: поле соответствует ТЗ.",
             "source_unit_ids": [unit["source_unit_id"]], "anchor_source_unit_id": unit["source_unit_id"]}
            for index, unit in enumerate(units, start=1)
        ],
        "coverage": [
            {"source_unit_id": unit["source_unit_id"], "disposition": "ATOMIZED", "reason": "Independent requirement"}
            for unit in units
        ], "warnings": [],
    }


class NativePacketTests(unittest.TestCase):
    def test_archive_references_reach_actual_prompt_without_paths(self):
        version = archive_version()
        packet = packet_for(version=version)
        messages = build_batch_messages(build_source_batches(packet)[0], 1)
        payload = json.loads(messages[1]["content"])
        self.assertIn("REFERENCE-ONLY", payload["methodology"]["instructions"])
        self.assertNotIn("references/detail.md", messages[1]["content"])
        self.assertNotIn("SKILL.md", messages[1]["content"])
        self.assertNotIn(version.content_sha256, messages[1]["content"])
        self.assertEqual(set(payload["methodology"]), {"instructions", "rules"})

    def test_saved_archive_and_compiled_text_are_both_pinned(self):
        for mutation in ("blob", "instructions"):
            with self.subTest(mutation=mutation):
                version = archive_version()
                if mutation == "blob":
                    version.package_blob += b"tamper"
                else:
                    version.instructions_text += "tamper"
                with self.assertRaises(CanonicalAtomizationError):
                    build_methodology_snapshot(version)

    def test_methodology_utf8_budget_is_enforced(self):
        with self.assertRaises(CanonicalAtomizationError) as raised:
            build_methodology_snapshot(json_version("\u044f" * 65537))
        self.assertEqual(raised.exception.code, "methodology_too_large")

    def test_pinned_docx_and_external_relationship_checks(self):
        data = docx(["Show status."], external=True)
        with self.assertRaises(CanonicalAtomizationError) as raised:
            build_native_preflight(data, run_id="r", source_sha256=sha256(data).hexdigest(),
                                   binding_id="binding", methodology=build_methodology_snapshot(json_version()))
        self.assertEqual(raised.exception.code, "external_office_relationship")
        with self.assertRaises(CanonicalAtomizationError) as raised:
            build_native_preflight(data, run_id="r", source_sha256="a" * 64,
                                   binding_id="binding", methodology=build_methodology_snapshot(json_version()))
        self.assertEqual(raised.exception.code, "document_hash_changed")

    def test_pdf_uses_exact_bytes_page_locators_and_native_privacy(self):
        data = pdf(["Document 1909-02-0111. Show status.", "Hide status for a different role."])
        digest = sha256(data).hexdigest()
        methodology = build_methodology_snapshot(json_version())
        prepared = build_native_preflight(
            data, run_id="pdf-test", source_sha256=digest, binding_id=document_binding_id(digest),
            methodology=methodology, source_kind="pdf",
        )
        packet = prepared.prompt_packet
        self.assertEqual(prepared.identity_report["source"]["kind"], "pdf")
        self.assertEqual([unit["source_locator"] for unit in packet["source_units"]],
                         ["PDF, стр. 1, блок 1", "PDF, стр. 2, блок 1"])
        self.assertEqual(packet["source_sha256"], digest)
        self.assertTrue(all(unit["source_kind"] == "page_text" for unit in packet["source_units"]))
        validate_native_prompt(packet, run_id="pdf-test", source_sha256=digest,
                               methodology=methodology, source_kind="pdf")
        outbound = json.dumps(build_batch_messages(build_source_batches(packet)[0], 1))
        self.assertNotIn("1909-02-0111", outbound)
        self.assertNotIn(digest, outbound)
        with self.assertRaises(CanonicalAtomizationError) as raised:
            build_native_preflight(data + b"tamper", run_id="pdf-test", source_sha256=digest,
                                   binding_id=document_binding_id(digest), methodology=methodology, source_kind="pdf")
        self.assertEqual(raised.exception.code, "document_hash_changed")

    def test_pdf_rejects_encryption_excess_pages_and_empty_scans(self):
        examples = [
            (pdf(["Protected text"], encrypted=True), "encrypted_pdf"),
            (pdf([None] * 301), "pdf_too_many_pages"),
            (pdf([None]), "document_text_empty"),
        ]
        for data, expected_code in examples:
            with self.subTest(code=expected_code):
                with self.assertRaises(CanonicalAtomizationError) as raised:
                    build_native_preflight(
                        data, run_id="pdf-test", source_sha256=sha256(data).hexdigest(), binding_id="binding",
                        methodology=build_methodology_snapshot(json_version()), source_kind="pdf",
                    )
                self.assertEqual(raised.exception.code, expected_code)
                if expected_code == "document_text_empty":
                    self.assertIn("OCR", raised.exception.message)

    def test_pdf_copy_requires_native_opt_in_and_preserves_bytes(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            data = pdf(["Show status."])
            (root / "source.pdf").write_bytes(data)
            document = SimpleNamespace(stored_filename="source.pdf", original_filename="source.pdf",
                                       sha256=sha256(data).hexdigest())
            with patch.object(settings, "UPLOAD_DIR", directory), patch.object(settings, "AUDIT_TZ_RUNTIME_DIR", str(root / "runtime")):
                with self.assertRaises(AuditTZRuntimeError) as raised:
                    _copy_source(uuid4(), document)
                self.assertEqual(raised.exception.code, "unsupported_document_type")
                copied = _copy_source(uuid4(), document, binding_id=document_binding_id(document.sha256), allow_pdf=True)
                self.assertEqual(copied.suffix, ".pdf")
                self.assertEqual(copied.read_bytes(), data)

    def test_document_and_methodology_requisites_are_masked_together(self):
        version = json_version(
            "\u0414\u043e\u0433\u043e\u0432\u043e\u0440 \u2116 EXAMPLE-2026-991. Template /private/example.docx " + "a" * 64,
            ["Follow EXAMPLE-2026-991 without copying the identifier."],
        )
        packet = packet_for(["Show status for EXAMPLE-2026-991."], version)
        batch = build_source_batches(packet)[0]
        outbound = json.dumps(build_batch_messages(batch, 1), ensure_ascii=False)
        for forbidden in ("EXAMPLE-2026-991", "/private", "example.docx", "a" * 64, packet["source_sha256"]):
            self.assertNotIn(forbidden, outbound)
        self.assertGreater(batch.redaction_count, 0)
        self.assertIn("EXAMPLE-2026-991", packet["source_units"][0]["text"])

    def test_credentials_fail_closed_in_methodology_and_source(self):
        for source in (True, False):
            with self.subTest(source=source):
                packet = packet_for(
                    ["password=synthetic-value" if source else "Show status."],
                    json_version("Keep requirements." if source else "api_key=synthetic-value"),
                )
                with self.assertRaises(CanonicalAtomizationError) as raised:
                    build_source_batches(packet)
                self.assertEqual(raised.exception.code, "privacy_sensitive_content")

    def test_snapshot_change_invalidates_prompt_and_checkpoint(self):
        packet = packet_for()
        batch = build_source_batches(packet)[0]
        saved = validate_batch_result(model_payload(batch.units), batch).as_storage()
        for field in ("instructions", "rules", "provider_context"):
            with self.subTest(field=field):
                changed = deepcopy(packet)
                if field == "instructions":
                    changed["methodology"]["instructions"] += " Changed reference content."
                elif field == "rules":
                    changed["methodology"]["rules"].append("A new rule.")
                else:
                    changed["provider_context"] = {"id": "provider", "config_version": 2, "model_name": "changed"}
                with self.assertRaises(CanonicalAtomizationError):
                    validate_native_prompt(changed, run_id="native-test", source_sha256=packet["source_sha256"],
                                           methodology=packet["methodology"])
                with self.assertRaises(CanonicalAtomizationError) as raised:
                    restore_batch_result(saved, build_source_batches(changed)[0])
                self.assertEqual(raised.exception.code, "atomization_checkpoint_invalid")

    def test_native_validation_keeps_same_title_different_requirements(self):
        packet = packet_for(["Screen A requires status.", "Screen B prohibits status."])
        batch = build_source_batches(packet)[0]
        result = validate_batch_result(model_payload(batch.units), batch)
        assembled = validate_native_atomization(packet, [result], model_name="mock")
        self.assertEqual(len(assembled.drafts), 2)
        self.assertNotEqual(assembled.drafts[0].source_refs, assembled.drafts[1].source_refs)
        self.assertFalse(any("consensus" in warning.lower() for warning in assembled.warnings))

    def test_native_validation_revalidates_cached_payload(self):
        packet = packet_for()
        batch = build_source_batches(packet)[0]
        result = validate_batch_result(model_payload(batch.units), batch)
        result.atoms[0]["source_unit_ids"] = ["UNKNOWN"]
        with self.assertRaises(CanonicalAtomizationError):
            validate_native_atomization(packet, [result], model_name="mock")

    def test_verification_notes_are_required_and_prompt_keeps_other_obligations(self):
        packet = packet_for(["Show status.", "Unresolved acceptance criterion.", "Provide training."])
        batch = build_source_batches(packet)[0]
        prompt = build_batch_messages(batch, 1)
        self.assertIn("Условия проверки:", prompt[0]["content"])
        self.assertIn("Ожидаемый результат:", prompt[0]["content"])
        self.assertIn("QUESTION", prompt[0]["content"])
        payload = model_payload(batch.units)
        payload["atoms"] = payload["atoms"][:1]
        payload["coverage"][1].update(disposition="QUESTION", reason="Acceptance criterion must be clarified.")
        payload["coverage"][2].update(disposition="OUT_OF_SCOPE", reason="Training obligation retained outside programmable atoms.")
        result = validate_batch_result(payload, batch)
        assembled = validate_native_atomization(packet, [result], model_name="mock")
        self.assertEqual(assembled.coverage_summary["QUESTION"], 1)
        self.assertEqual(assembled.coverage_summary["OUT_OF_SCOPE"], 1)
        self.assertEqual(assembled.package["coverage"][2]["reason"], payload["coverage"][2]["reason"])
        payload["atoms"][0]["notes"] = None
        with self.assertRaises(CanonicalAtomizationError) as raised:
            validate_batch_result(payload, batch)
        self.assertEqual(raised.exception.code, "invalid_model_schema")


class MemorySession:
    def __init__(self, document, version):
        actor_id, case_id, run_id = uuid4(), uuid4(), uuid4()
        document.case_id = case_id
        self.actor = SimpleNamespace(id=actor_id, role=UserRole.admin, is_active=True, audit_enabled=True)
        self.membership = SimpleNamespace(role="member")
        self.case = SimpleNamespace(id=case_id, status="atomization", workflow_stage="atomization",
                                    responsible_user_id=actor_id, digital_product="Synthetic product")
        self.run = SimpleNamespace(
            id=run_id, case_id=case_id, document_id=document.id, skill_version_id=version.id,
            source_sha256=document.sha256, skill_sha256=version.content_sha256,
            source_binding="document_hash", requested_by_id=actor_id, status="running",
            source_unit_count=0, completed_batch_count=0, total_batch_count=0,
            safe_summary_json={}, external_ai_called=False,
        )
        self.job = SimpleNamespace(id=uuid4(), run_id=run_id, status="running", lease_token="lease", pause_requested_at=None)
        self.provider = SimpleNamespace(
            id=uuid4(), display_name="Mock", model_name="mock", config_version=1,
            enabled=True, last_test_status="ok", last_verified_config_version=1,
            base_url="https://unused.invalid", api_key_ciphertext=None,
        )
        self.attempt = SimpleNamespace(
            id=uuid4(), case_id=case_id, canonical_run_id=run_id, document_id=document.id,
            skill_version_id=version.id, document_sha256=document.sha256, skill_sha256=version.content_sha256,
            status="running", provider_config_id=self.provider.id, provider_config_version=1,
            model_name="mock", requested_by_id=actor_id, batch_results_json=[], config_version=1,
        )
        self.objects = {
            AuditTZRun: self.run, AuditTZRuntimeJob: self.job, AuditDocument: document,
            AuditAtomizationSkillVersion: version, AuditAtomizationSkill: SimpleNamespace(is_enabled=True),
            AuditCase: self.case, AIProviderConfig: self.provider,
        }
        self.added, self.locks, self.queries = [], [], []
        self.human_atoms = [SimpleNamespace(title="Human decision", state="approved")]

    async def get(self, model, _key):
        return self.objects.get(model)

    async def scalar(self, query):
        self.queries.append(str(query))
        entity = query.column_descriptions[0]["entity"]
        if query._for_update_arg is not None:
            self.locks.append(entity)
        if entity is AuditTZArtifact:
            kind = query.compile().params["kind_1"]
            artifact = next((item for item in self.added if isinstance(item, AuditTZArtifact) and item.kind == kind), None)
            return artifact.sha256 if artifact and query.column_descriptions[0]["name"] == "sha256" else artifact
        if entity is AuditAIAtomizationAttempt:
            return self.attempt
        if entity is AuditAIModelRegistry:
            return next((item for item in self.added if isinstance(item, AuditAIModelRegistry)), None)
        if entity is User:
            return self.actor
        if entity is AuditTeamMember:
            return self.membership
        return self.objects.get(entity)

    def add(self, item):
        if getattr(item, "id", None) is None:
            item.id = uuid4()
        self.added.append(item)

    async def execute(self, _query):
        return None

    async def flush(self):
        return None

    async def commit(self):
        return None

    async def rollback(self):
        return None

    @asynccontextmanager
    async def begin_nested(self):
        yield self

    @asynccontextmanager
    async def factory(self):
        yield self


class NativeWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_trusted_cached_batch_resumes_with_original_payload_hash(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            version = json_version("Legacy trusted instructions must not be reinjected.", ["Legacy rule."])
            version.package_format = "trusted_skill_archive"
            db = MemorySession(SimpleNamespace(id=uuid4(), sha256="a" * 64), version)
            units = [source_unit(index, f"Independent field {index}.") for index in range(1, 34)]
            units[0] = source_unit(1, "Договор № LEGACY-2026-991.")
            units[1] = source_unit(2, "Параметры LEGACY-2026-991 используются в форме.")
            packet = legacy_prompt_packet(units)
            # Freeze the deployed outbound representation, including its punctuation behavior.
            old_outbound = [{"source_unit_id": unit["source_unit_id"], "text": unit["text"]} for unit in units[:32]]
            old_outbound[0]["text"] = "Договор № [РЕКВИЗИТ-СКРЫТ]"
            old_payload = model_payload(old_outbound)
            old_payload["atoms"] = old_payload["atoms"][:1]
            old_payload["atoms"][0]["title"] = "Previously captured requirement"
            for item in old_payload["coverage"][1:]:
                item.update(disposition="NON_REQUIREMENT", reason="Reviewed context")
            for atom in old_payload["atoms"]:
                atom.update(work_type=None, notes=None, confidence=None)
            cached = {
                "batch_index": 1,
                "payload_hash": sha256(json.dumps(old_outbound, ensure_ascii=False, sort_keys=True,
                                                     separators=(",", ":")).encode("utf-8")).hexdigest(),
                **old_payload, "response_sha256": "d" * 64, "redaction_count": 1,
            }
            db.attempt.batch_results_json = [deepcopy(cached)]
            drafts = root / "runs" / str(db.run.id) / "contracts" / "contract" / "drafts"
            drafts.mkdir(parents=True)
            (drafts / "primary-prompt-packet.json").write_text(json.dumps(packet), encoding="utf-8")

            async def cli(_root, command, args, **_kwargs):
                if command == "validate-atoms":
                    generated = Path(args[args.index("--input") + 1])
                    (drafts / "primary.validated.json").write_bytes(generated.read_bytes())
                else:
                    self.assertEqual(command, "export-prompt")

            async def model(_provider, messages, **_kwargs):
                outbound = json.loads(messages[1]["content"])
                self.assertNotIn("methodology", outbound)
                self.assertNotIn("provider_context", outbound)
                self.assertEqual(outbound["protocol"], "dpms-canonical-audit-atomization-v1")
                self.assertEqual(outbound["source_units"], [{"source_unit_id": "U000033", "text": units[32]["text"]}])
                return json.dumps(model_payload(outbound["source_units"]))

            generate = AsyncMock(side_effect=model)
            with (
                patch.object(settings, "AUDIT_TZ_RUNTIME_DIR", directory),
                patch.object(settings, "AUDIT_TZ_EXTERNAL_AI_ENABLED", True),
                patch("app.services.audit_tz_runtime._skill_directory", return_value=root),
                patch("app.services.audit_tz_runtime._run_cli", new=AsyncMock(side_effect=cli)),
                patch("app.services.audit_tz_runtime._complete_job", new=AsyncMock(return_value=db.job)),
                patch("app.services.audit_tz_runtime._renew_job_lease", new=AsyncMock()),
                patch("app.services.audit_tz_runtime._pause_atomization_if_requested", new=AsyncMock(return_value=False)),
                patch("app.services.audit_tz_runtime.publish_model_registry_atoms",
                      new=AsyncMock(return_value=SimpleNamespace(atoms_created=1, atom_ids=[]))),
                patch("app.services.audit_tz_atomization.generate_text", generate),
            ):
                await process_atomization(db.job.id, "lease", db.factory)
            self.assertEqual(db.run.status, "draft_ready")
            self.assertEqual(generate.await_count, 1)
            self.assertEqual(db.attempt.batch_results_json[0], cached)
            self.assertEqual(db.attempt.prompt_sha256, packet["prompt_packet_hash"])
            self.assertEqual(db.run.completed_batch_count, 2)
            self.assertEqual(len([item for item in db.added if isinstance(item, AuditAIModelRegistry)]), 1)

    async def test_schema_retry_keeps_selected_instructions_and_rules(self):
        packet = packet_for(version=json_version("UNIQUE selected instruction.", ["UNIQUE selected rule."]))
        batch = build_source_batches(packet)[0]
        generate = AsyncMock(side_effect=["{}", json.dumps(model_payload(batch.units))])
        with patch("app.services.audit_tz_atomization.generate_text", generate), patch(
            "app.services.audit_tz_runtime.asyncio.sleep", new=AsyncMock(),
        ):
            await _generate_batch_with_retry(SimpleNamespace(), batch, 1)
        self.assertEqual(generate.await_count, 2)
        for call in generate.await_args_list:
            payload = json.loads(call.args[1][1]["content"])
            self.assertIn("UNIQUE selected instruction", payload["methodology"]["instructions"])
            self.assertEqual(payload["methodology"]["rules"], ["UNIQUE selected rule."])

    async def _lifecycle(self, *, interrupted=False, late_stage=None, archived=False, revoked=False, rejected=False,
                         source_kind="docx", declarative_json=False):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            texts = [f"Screen {index} has an independent status field." for index in range(33)]
            data = pdf(texts) if source_kind == "pdf" else docx(texts)
            filename = f"source.{source_kind}"
            (root / filename).write_bytes(data)
            document = SimpleNamespace(id=uuid4(), sha256=sha256(data).hexdigest(),
                                       original_filename=filename, stored_filename=filename)
            version = json_version("REFERENCE-ONLY: preserve distinct requirements.") if declarative_json else archive_version()
            db = MemorySession(document, version)

            async def model(_provider, messages, **_kwargs):
                payload = json.loads(messages[1]["content"])
                self.assertIn("REFERENCE-ONLY", payload["methodology"]["instructions"])
                return json.dumps(model_payload(payload["source_units"]))

            generate = AsyncMock(side_effect=model)
            publish = AsyncMock(return_value=SimpleNamespace(atoms_created=33, atom_ids=[]))
            if rejected:
                publish.side_effect = HTTPException(status_code=409, detail="Synthetic publication conflict")
            with (
                patch.object(settings, "UPLOAD_DIR", directory),
                patch.object(settings, "AUDIT_TZ_RUNTIME_DIR", str(root / "runtime")),
                patch.object(settings, "AUDIT_TZ_EXTERNAL_AI_ENABLED", True),
                patch("app.services.audit_tz_runtime._run_cli", new=AsyncMock(side_effect=AssertionError("native invoked CLI"))),
                patch("app.services.audit_tz_runtime._skill_directory", side_effect=AssertionError("native extracted skill")),
                patch("app.services.audit_tz_runtime._complete_job", new=AsyncMock(return_value=db.job)),
                patch("app.services.audit_tz_runtime._renew_job_lease", new=AsyncMock()),
                patch("app.services.audit_tz_atomization.generate_text", generate),
                patch("app.services.audit_tz_runtime.publish_model_registry_atoms", publish),
            ):
                await process_preflight(db.job.id, "lease", db.factory)
                self.assertEqual(db.run.status, "preflight_pass")
                self.assertEqual(db.run.safe_summary_json["runtime_engine"], NATIVE_PROTOCOL)
                self.assertEqual(db.run.safe_summary_json["source_kind"], source_kind)
                self.assertEqual({item.kind for item in db.added if isinstance(item, AuditTZArtifact)},
                                 {"identity_report", "source_units", "gated_evidence_bundle", "primary_prompt"})
                self.assertFalse(db.run.external_ai_called)
                if interrupted:
                    with patch("app.services.audit_tz_runtime._pause_atomization_if_requested",
                               new=AsyncMock(side_effect=[False, False, True])):
                        await process_atomization(db.job.id, "lease", db.factory)
                    self.assertEqual(len(db.attempt.batch_results_json), 1)
                    self.assertFalse(any(isinstance(item, AuditAIModelRegistry) for item in db.added))
                if late_stage:
                    db.case.workflow_stage = late_stage
                if archived:
                    db.case.status = "archived"
                if revoked:
                    db.actor.is_active = False
                db.locks.clear()
                with patch("app.services.audit_tz_runtime._pause_atomization_if_requested", new=AsyncMock(return_value=False)):
                    await process_atomization(db.job.id, "lease", db.factory)
                self.assertEqual(generate.await_count, 2)
                self.assertEqual(db.run.status, "draft_ready")
                self.assertEqual(db.run.completed_batch_count, 2)
                self.assertEqual(len([item for item in db.added if isinstance(item, AuditAIModelRegistry)]), 1)
                self.assertEqual(len([item for item in db.added if isinstance(item, AuditAIModelRegistryItem)]), 33)
                self.assertEqual(db.human_atoms[0].state, "approved")
                self.assertFalse(any("count(audit_atoms" in query for query in db.queries))
                self.assertEqual(db.locks[:3], [AuditCase, AuditTZRuntimeJob, AuditAIAtomizationAttempt])
                blocker = (
                    "case_archived" if archived else "case_stage_changed" if late_stage
                    else "initiator_inactive" if revoked else "publication_rejected_409" if rejected else None
                )
                self.assertEqual(db.run.safe_summary_json["autoappend_blocker"], blocker)
                self.assertEqual(publish.await_count, 0 if late_stage or archived or revoked else 1)
                self.assertEqual(db.run.safe_summary_json["atoms_appended"], 0 if blocker else 33)
                self.assertEqual(db.case.workflow_stage, late_stage or "atomization")

    async def test_native_worker_creates_independent_registry_for_populated_case(self):
        await self._lifecycle()

    async def test_native_resume_reuses_completed_batches(self):
        await self._lifecycle(interrupted=True)

    async def test_pdf_archive_native_resume_reuses_completed_batches(self):
        await self._lifecycle(source_kind="pdf", interrupted=True)

    async def test_pdf_declarative_json_creates_native_registry(self):
        await self._lifecycle(source_kind="pdf", declarative_json=True)

    async def test_late_stage_keeps_registry_without_implicit_reopen(self):
        await self._lifecycle(late_stage="verification")

    async def test_archived_case_keeps_model_result_without_publication(self):
        await self._lifecycle(archived=True)

    async def test_revoked_initiator_keeps_model_result_without_publication(self):
        await self._lifecycle(revoked=True)

    async def test_publication_conflict_does_not_discard_model_result(self):
        await self._lifecycle(rejected=True)

    async def test_publication_rechecks_current_actor_access(self):
        db = MemorySession(SimpleNamespace(id=uuid4(), sha256="a" * 64), json_version())
        self.assertIsNone(await _registry_autoappend_blocker(db, db.case, db.actor.id))
        db.actor.is_active = False
        self.assertEqual(await _registry_autoappend_blocker(db, db.case, db.actor.id), "initiator_inactive")
        db.actor.is_active = True
        db.actor.role = "employee"
        db.actor.audit_enabled = False
        self.assertEqual(await _registry_autoappend_blocker(db, db.case, db.actor.id), "audit_access_revoked")
        db.actor.audit_enabled = True
        db.membership = None
        self.assertEqual(await _registry_autoappend_blocker(db, db.case, db.actor.id), "audit_membership_revoked")
        db.membership = SimpleNamespace(role="member")
        db.case.responsible_user_id = uuid4()
        self.assertEqual(await _registry_autoappend_blocker(db, db.case, db.actor.id), "atom_editor_permission_revoked")
        db.membership.role = "leader"
        self.assertIsNone(await _registry_autoappend_blocker(db, db.case, db.actor.id))
        db.case.status = "archived"
        self.assertEqual(await _registry_autoappend_blocker(db, db.case, db.actor.id), "case_archived")
