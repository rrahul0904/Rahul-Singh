import asyncio
import io
import os
import sys
import zipfile
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy.sql import operators
from sqlalchemy.sql.dml import Delete
from sqlalchemy.sql.selectable import Select

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from agents.migration_intelligence_orchestrator import MigrationIntelligenceOrchestrator  # noqa: E402
from api.routes.intelligence import (  # noqa: E402
    IntelligenceRunCreate,
    create_run,
    download_docx,
    get_artifact,
    get_run,
    list_artifacts,
    list_runs,
    download_markdown,
    download_pdf,
    preview_report,
    upload_artifact,
)
from core.auth import get_current_user  # noqa: E402
from models import (  # noqa: E402
    ArtifactChunk,
    ArtifactExtraction,
    MigrationIntelligenceReport,
    MigrationIntelligenceRun,
    UploadedArtifact,
    User,
    UserRole,
)
from services.migration_intelligence_backend import (  # noqa: E402
    MAX_UPLOAD_BYTES,
    MigrationIntelligenceArtifactService,
    extract_references,
    parse_artifact_bytes,
)


def build_test_pdf(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
    objects = [
        "1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        "2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
        "3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n",
        "4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
        f"5 0 obj << /Length {len(stream)} >> stream\n{stream}\nendstream endobj\n",
    ]
    pdf = "%PDF-1.4\n"
    offsets = []
    for obj in objects:
        offsets.append(len(pdf.encode("latin-1")))
        pdf += obj
    xref = len(pdf.encode("latin-1"))
    pdf += f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n"
    for offset in offsets:
        pdf += f"{offset:010d} 00000 n \n"
    pdf += f"trailer << /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF"
    return pdf.encode("latin-1")


class FakeResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return self

    def all(self):
        return list(self._items)

    def scalar_one_or_none(self):
        if not self._items:
            return None
        if len(self._items) > 1:
            raise AssertionError("Expected one or zero rows")
        return self._items[0]


class FakeAsyncSession:
    def __init__(self):
        self.storage = {}

    def add(self, obj):
        cls = type(obj)
        self.storage.setdefault(cls, [])
        if obj not in self.storage[cls]:
            self._apply_defaults(obj)
            self.storage[cls].append(obj)

    def _apply_defaults(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = str(uuid4())
        now = datetime.utcnow()
        for attr in ("created_at", "updated_at", "started_at"):
            if hasattr(obj, attr) and getattr(obj, attr) is None and attr in {"created_at", "started_at"}:
                setattr(obj, attr, now)

    async def flush(self):
        for items in self.storage.values():
            for obj in items:
                self._apply_defaults(obj)

    async def commit(self):
        await self.flush()

    async def refresh(self, obj):
        self._apply_defaults(obj)

    async def get(self, model, obj_id):
        for obj in self.storage.get(model, []):
            if getattr(obj, "id", None) == obj_id:
                return obj
        return None

    async def execute(self, stmt):
        if isinstance(stmt, Delete):
            model = self._model_for_table(stmt.table.name)
            items = self.storage.get(model, [])
            kept = [obj for obj in items if not self._matches_where(obj, stmt._where_criteria)]
            self.storage[model] = kept
            return FakeResult([])
        if not isinstance(stmt, Select):
            raise AssertionError(f"Unsupported statement type: {type(stmt)}")
        model = stmt.column_descriptions[0]["entity"]
        items = [obj for obj in self.storage.get(model, []) if self._matches_where(obj, stmt._where_criteria)]
        return FakeResult(items)

    def _model_for_table(self, table_name: str):
        for model in (UploadedArtifact, ArtifactExtraction, ArtifactChunk, MigrationIntelligenceRun, MigrationIntelligenceReport):
            if model.__tablename__ == table_name:
                return model
        raise AssertionError(f"Unknown table {table_name}")

    def _matches_where(self, obj, criteria):
        if not criteria:
            return True
        return all(self._eval_criterion(obj, criterion) for criterion in criteria)

    def _eval_criterion(self, obj, criterion):
        left_name = getattr(getattr(criterion, "left", None), "name", None)
        if left_name is None:
            return True
        left_value = getattr(obj, left_name)
        right = getattr(criterion, "right", None)
        right_value = getattr(right, "value", right)
        if criterion.operator == operators.eq:
            return left_value == right_value
        if criterion.operator == operators.in_op:
            return left_value in list(right_value)
        raise AssertionError(f"Unsupported operator {criterion.operator}")


def make_upload(filename: str, payload: bytes, content_type: str) -> UploadFile:
    return UploadFile(file=io.BytesIO(payload), filename=filename, headers={"content-type": content_type})


def test_unauthenticated_dependency_rejects_access():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(get_current_user(None))
    assert exc.value.status_code == 401


def test_sql_txt_md_pdf_and_failed_pdf_classification():
    sql = parse_artifact_bytes("orders.sql", ".sql", b"CREATE TABLE sales.orders (id INT, updated_at TIMESTAMP);")
    txt = parse_artifact_bytes("reqs.txt", ".txt", b"Requirement: preserve rollback and row counts.")
    md = parse_artifact_bytes("mapping.md", ".md", b"# Mapping\nsource column to target column")
    pdf = parse_artifact_bytes("package.pdf", ".pdf", build_test_pdf("CREATE PACKAGE finance_pkg AS END;"))
    scanned = parse_artifact_bytes("scanned.pdf", ".pdf", b"%PDF-1.4\n1 0 obj <<>> endobj\n%%EOF")

    assert sql.classification == "SQL"
    assert sql.source_system_guess == "Generic SQL"
    assert txt.classification == "REQUIREMENTS"
    assert md.classification == "MAPPING_DOC"
    assert pdf.classification == "PL_SQL"
    assert pdf.metadata["packages"] == ["finance_pkg"]
    assert scanned.extraction_status == "NEEDS_OCR_NOT_SUPPORTED"


def test_dependency_extraction_ignores_narrative_stopwords():
    refs = extract_references(
        "Need mapping from source tables to Snowflake target tables.",
        "REQUIREMENTS",
    )
    assert refs["dependencies"] == []
    assert refs["dependency_evidence_strength"] == "weak"
    assert "mapping" in refs["ignored_dependency_candidates"]
    assert "No strong dependency evidence was detected from the uploaded requirement text." in refs["dependency_evidence_notes"]


def test_dependency_extraction_keeps_valid_object_names():
    refs = extract_references(
        "Procedure finance_pkg.calculate_revenue depends on raw.orders and raw.customers.",
        "REQUIREMENTS",
    )
    assert refs["dependencies"] == [
        "finance_pkg.calculate_revenue",
        "raw.customers",
        "raw.orders",
    ]
    assert "finance_pkg.calculate_revenue" in refs["procedures"]

    convert_refs = extract_references("Convert customer_dim and order_fact to Snowflake.", "REQUIREMENTS")
    assert convert_refs["dependencies"] == ["customer_dim", "order_fact"]


def test_service_upload_and_chunk_creation():
    db = FakeAsyncSession()
    user = User(id="user-1", email="mi@example.com", name="MI", password_hash="x", role=UserRole.admin, is_active=True)
    service = MigrationIntelligenceArtifactService(db)

    artifact = asyncio.run(
        service.upload_artifact(
            make_upload(
                "orders.sql",
                b"CREATE TABLE sales.orders (id INT); INSERT INTO sales.orders VALUES (1);",
                "text/plain",
            ),
            user,
        )
    )
    extraction = asyncio.run(service.get_extraction(artifact.id))
    chunks = asyncio.run(service.get_chunks(artifact.id))

    assert artifact.extraction_status == "CLASSIFIED"
    assert extraction.extracted_text_preview
    assert len(chunks) >= 2
    assert any(chunk.statement_type == "DDL" for chunk in chunks)
    assert any(chunk.statement_type == "DML" for chunk in chunks)


def test_upload_validation_rejects_unsupported_empty_and_oversized_files():
    db = FakeAsyncSession()
    user = User(id="user-1", email="mi@example.com", name="MI", password_hash="x", role=UserRole.admin, is_active=True)
    service = MigrationIntelligenceArtifactService(db)

    with pytest.raises(HTTPException) as unsupported:
        asyncio.run(service.upload_artifact(make_upload("notes.csv", b"id,name\n1,a\n", "text/csv"), user))
    assert unsupported.value.status_code == 415

    with pytest.raises(HTTPException) as empty:
        asyncio.run(service.upload_artifact(make_upload("empty.sql", b"", "text/plain"), user))
    assert empty.value.status_code == 400

    with pytest.raises(HTTPException) as oversized:
        asyncio.run(service.upload_artifact(make_upload("large.sql", b"x" * (MAX_UPLOAD_BYTES + 1), "text/plain"), user))
    assert oversized.value.status_code == 413


def test_upload_route_returns_shape_and_list_refreshes():
    db = FakeAsyncSession()
    user = User(id="user-1", email="mi@example.com", name="MI", password_hash="x", role=UserRole.admin, is_active=True)

    first = asyncio.run(
        upload_artifact(
            file=make_upload("first.sql", b"CREATE TABLE raw.orders (id INT);", "text/plain"),
            user=user,
            db=db,
        )
    )
    second = asyncio.run(
        upload_artifact(
            file=make_upload("second.md", b"# Notes\nConvert customer_dim and order_fact to Snowflake.", "text/markdown"),
            user=user,
            db=db,
        )
    )
    listed = asyncio.run(list_artifacts(_user=user, db=db))

    assert sorted(first.keys()) == sorted(
        [
            "id",
            "file_name",
            "file_type",
            "mime_type",
            "size_bytes",
            "sha256_hash",
            "storage_path",
            "uploaded_by",
            "created_at",
            "extraction_status",
            "extracted_text_preview",
            "classification",
            "language_guess",
            "source_system_guess",
            "error_message",
            "extraction",
            "chunks",
        ]
    )
    assert first["extraction"]["artifact_id"] == first["id"]
    assert isinstance(first["chunks"], list)
    assert {row["file_name"] for row in listed} == {"first.sql", "second.md"}
    assert second["classification"] in {"REQUIREMENTS", "MAPPING_DOC"}


def test_missing_artifact_and_report_ids_return_404s():
    db = FakeAsyncSession()
    user = User(id="user-1", email="mi@example.com", name="MI", password_hash="x", role=UserRole.admin, is_active=True)

    with pytest.raises(HTTPException) as artifact_exc:
        asyncio.run(get_artifact("missing-artifact", _user=user, db=db))
    assert artifact_exc.value.status_code == 404

    with pytest.raises(HTTPException) as run_exc:
        asyncio.run(create_run(IntelligenceRunCreate(selected_artifact_ids=["missing-artifact"]), user=user, db=db))
    assert run_exc.value.status_code == 404

    for endpoint in (download_markdown, download_pdf, download_docx, preview_report):
        with pytest.raises(HTTPException) as report_exc:
            asyncio.run(endpoint("missing-report", _user=user, db=db))
        assert report_exc.value.status_code == 404


def test_orchestrator_run_and_export_routes():
    db = FakeAsyncSession()
    user = User(id="user-1", email="mi@example.com", name="MI", password_hash="x", role=UserRole.admin, is_active=True)
    service = MigrationIntelligenceArtifactService(db)

    sql_artifact = asyncio.run(
        service.upload_artifact(
            make_upload(
                "orders.sql",
                b"CREATE TABLE sales.orders (id INT); INSERT INTO sales.orders VALUES (1);",
                "text/plain",
            ),
            user,
        )
    )
    txt_artifact = asyncio.run(
        service.upload_artifact(
            make_upload("requirements.txt", b"Requirement: preserve rollback planning.", "text/plain"),
            user,
        )
    )
    pdf_artifact = asyncio.run(
        service.upload_artifact(
            make_upload("package.pdf", build_test_pdf("CREATE PACKAGE finance_pkg AS END;"), "application/pdf"),
            user,
        )
    )

    response = asyncio.run(
        create_run(
            IntelligenceRunCreate(selected_artifact_ids=[sql_artifact.id, txt_artifact.id, pdf_artifact.id]),
            user=user,
            db=db,
        )
    )
    run_id = response["id"]
    report_id = response["report_id"]
    report = asyncio.run(db.get(MigrationIntelligenceReport, report_id))

    assert response["openai_called"] is False
    assert response["snowflake_cortex_called"] is False
    assert response["snowflake_sql_executed"] is False
    assert response["uploaded_sql_executed"] is False
    assert response["generated_code_executed"] is False
    assert response["ddl_executed"] is False
    assert response["data_moved"] is False
    assert report is not None
    assert "OpenAI called: No" in report.report_markdown
    assert "Snowflake SQL executed: No" in report.report_markdown
    assert "Packages: finance_pkg" in report.report_markdown
    assert "Dependencies: sales.orders" in report.report_markdown
    assert "Dependencies: mapping" not in report.report_markdown
    assert "Dependency and Lineage Findings" in report.report_markdown

    preview = asyncio.run(preview_report(report_id, _user=user, db=db))
    md = asyncio.run(download_markdown(report_id, _user=user, db=db))
    pdf = asyncio.run(download_pdf(report_id, _user=user, db=db))
    docx = asyncio.run(download_docx(report_id, _user=user, db=db))
    run_detail = asyncio.run(get_run(run_id, _user=user, db=db))
    run_rows = asyncio.run(list_runs(_user=user, db=db))

    assert preview["run_id"] == run_id
    assert run_detail["report_id"] == report_id
    assert run_rows[0]["report_id"] == report_id
    assert preview["flags"]["snowflake_sql_executed"] is False
    assert "OpenAI called: No" in md.body.decode("utf-8")
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.body.startswith(b"%PDF-")
    assert docx.headers["content-type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    with zipfile.ZipFile(io.BytesIO(docx.body)) as zf:
        document_xml = zf.read("word/document.xml").decode("utf-8")
        assert "OpenAI called: No" in document_xml
        assert "Generated code executed: No" in document_xml


def test_report_includes_dependency_limitation_for_weak_requirement_text():
    db = FakeAsyncSession()
    user = User(id="user-1", email="mi@example.com", name="MI", password_hash="x", role=UserRole.admin, is_active=True)
    service = MigrationIntelligenceArtifactService(db)

    requirement_artifact = asyncio.run(
        service.upload_artifact(
            make_upload(
                "weak_requirements.txt",
                b"Need mapping from source tables to Snowflake target tables.",
                "text/plain",
            ),
            user,
        )
    )

    response = asyncio.run(
        create_run(
            IntelligenceRunCreate(selected_artifact_ids=[requirement_artifact.id]),
            user=user,
            db=db,
        )
    )
    report = asyncio.run(db.get(MigrationIntelligenceReport, response["report_id"]))
    assert report is not None
    assert "No strong dependency evidence was detected from the uploaded requirement text." in report.report_markdown
    assert "Dependencies: mapping" not in report.report_markdown
