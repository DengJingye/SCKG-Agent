"""Synthetic parser/security fixtures; these are not scientific evaluation gold."""
import io
import socket
import zipfile

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from sckg_workbench.parsing import parse_document
from sckg_workbench.sources import (
    FetchResult, SourceError, SourceService, fetch_public_url, github_raw_url, validate_remote_url,
)
from sckg_workbench.storage import Ledger, Workspace


@pytest.fixture
def service(tmp_path):
    return SourceService(Ledger(Workspace(tmp_path / "fresh-workspace")))


def test_registration_is_provisional_and_byte_reuse_preserves_acquisitions(service):
    first = service.register_bytes("one.md", b"Synthetic test paragraph.", metadata={"title": "Synthetic fixture"})
    second = service.register_bytes("two.md", b"Synthetic test paragraph.")
    assert first["trust_status"] == second["trust_status"] == "unreviewed"
    assert first["identity_status"] == "provisional"
    assert first["source_id"] != second["source_id"]
    assert first["source_revision_id"] != second["source_revision_id"]
    assert first["acquisition_id"] != second["acquisition_id"]
    assert first["blob_sha256"] == second["blob_sha256"]
    assert len(list(service.blob_dir.iterdir())) == 1
    assert len(service.ledger.list_records("original")) == 2
    assert len(service.ledger.list_records("snapshot")) == 2
    assert len(service.ledger.list_records("acquisition")) == 2


@pytest.mark.parametrize("key", ["trust_status", "review_status", "identity_status", "trusted", "reviewed", "blob_path", "id"])
def test_metadata_cannot_assign_trust_or_storage(service, key):
    with pytest.raises(SourceError, match="cannot assign"):
        service.register_bytes("fixture.md", b"synthetic", metadata={key: "caller supplied"})
    assert not service.ledger.list_records("source")


def test_markdown_code_indentation_is_preserved(service):
    text = "  first line\n  second line\n\n    code block"
    ir = service.parse(service.register_bytes("indented.md", text.encode())["id"])
    assert ir["blocks"][0]["exact_text"].startswith("  first")
    assert ir["blocks"][1]["exact_text"] == "    code block"


def test_idempotency_persists_and_rejects_reused_request_payload(service):
    first = service.register_bytes("fixture.md", b"first", request_id="upload-1")
    reopened = SourceService(Ledger(service.workspace))
    assert reopened.register_bytes("fixture.md", b"first", request_id="upload-1") == first
    assert len(service.ledger.events()) == 1
    with pytest.raises(SourceError, match="different acquisition"):
        reopened.register_bytes("fixture.md", b"changed", request_id="upload-1")
    assert len(service.ledger.list_records("source")) == 1


def test_plain_text_locations_and_parse_idempotency(service):
    text = "# Synthetic fixture\nFirst paragraph.\n\n第二段 preserves words.\n"
    source = service.register_bytes("example.md", text.encode())
    ir = service.parse(source["id"])
    assert ir["status"] == "complete"
    assert len(ir["blocks"]) == 2
    for block in ir["blocks"]:
        loc = block["locator"]
        assert text[loc["source_char_start"]:loc["source_char_end"]] == block["exact_text"]
        assert ir["document_text"][loc["document_start"]:loc["document_end"]] == block["exact_text"]
        assert block["exact_text"][loc["block_start"]:loc["block_end"]] == block["exact_text"]
    assert service.parse(source["id"]) == ir
    assert len(service.ledger.list_records("document_ir")) == 1
    assert len(service.ledger.events(source["id"])) == 2


def test_partial_ir_does_not_claim_complete_and_has_distinct_id(service):
    source = service.register_bytes("example.txt", b"Long synthetic paragraph.\n\nAnother paragraph.")
    limited = service.parse(source["id"], max_chars=5)
    complete = service.parse(source["id"])
    assert limited["id"] != complete["id"]
    assert limited["status"] == "partial"
    assert limited["blocks"][0]["exact_text"] == "Long "
    assert limited["blocks"][0]["locator"]["source_char_end"] == 5
    assert not limited["coverage"]["text_extraction_complete"]
    with pytest.raises(ValueError):
        service.parse(source["id"], max_pages=0)


def _docx(xml):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", xml)
    return output.getvalue()


def test_docx_paragraph_and_table_cell_offsets(service):
    data = _docx('''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
      <w:p><w:r><w:t>Synthetic paragraph.</w:t></w:r></w:p>
      <w:tbl><w:tr><w:tc><w:p><w:r><w:t>Tool</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Scope</w:t></w:r></w:p></w:tc></w:tr>
      <w:tr><w:tc><w:p><w:r><w:t>Example</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Fixture only</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
      </w:body></w:document>''')
    source = service.register_bytes("fixture.docx", data)
    ir = service.parse(source["id"])
    assert ir["status"] == "complete"
    table = ir["blocks"][1]
    assert table["exact_text"] == "Tool\tScope\nExample\tFixture only"
    last = table["locator"]["cells"][-1]
    assert table["exact_text"][last["start"]:last["end"]] == "Fixture only"


@pytest.mark.parametrize("data", [
    b'<!DOCTYPE a [<!ENTITY x "expansion">]><a>&x;</a>',
    '<!DOCTYPE a [<!ENTITY x "expansion">]><a>&x;</a>'.encode("utf-16"),
])
def test_xml_entity_declarations_fail_closed(service, data):
    ir = service.parse(service.register_bytes("fixture.xml", data)["id"])
    assert ir["status"] == "parse_gap"
    assert ir["blocks"] == []
    assert ir["gaps"][0]["code"] == "parser_error"


def test_jats_xml_preserves_table_context_and_no_duplicate_paragraphs(service):
    data = b"<article><body><sec><title>Fixture</title><p>A <italic>test</italic> paragraph.</p><table-wrap><caption>Sample context</caption><table><tr><th>Name</th><th>Value</th></tr><tr><td>A</td><td>1</td></tr></table></table-wrap></sec></body></article>"
    ir = service.parse(service.register_bytes("fixture.xml", data)["id"])
    assert len(ir["blocks"]) == 3
    assert ir["blocks"][1]["exact_text"] == "A test paragraph."
    assert ir["blocks"][2]["exact_text"] == "Sample context\nName\tValue\nA\t1"
    assert ir["blocks"][2]["locator"]["path"].endswith("table-wrap[1]")


def test_html_does_not_execute_or_include_scripts_and_keeps_tables(service):
    html = b"<h1>Fixture</h1><script>erase_everything()</script><p>A <b>bold</b> statement.</p><table><tr><th>Name</th><th>Value</th></tr><tr><td>A</td><td>1</td></tr></table>"
    ir = service.parse(service.register_bytes("fixture.html", html)["id"])
    assert ir["status"] == "complete"
    assert "erase_everything" not in ir["document_text"]
    assert ir["blocks"][1]["exact_text"] == "A bold statement."
    assert ir["blocks"][2]["locator"]["kind"] == "html_table"
    assert "Name\tValue" in ir["blocks"][2]["exact_text"]


def _pdf(with_text=False, pages=1):
    writer = PdfWriter()
    for _ in range(pages):
        page = writer.add_blank_page(width=600, height=800)
        if with_text:
            font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
            page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
            stream = DecodedStreamObject()
            stream.set_data(b"BT /F1 12 Tf 50 700 Td (Synthetic PDF fixture.) Tj ET")
            page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pdf_text_page_limit_and_no_ocr_fabrication(service):
    blank = service.parse(service.register_bytes("scanned.pdf", _pdf())["id"])
    assert blank["status"] == "parse_gap"
    assert blank["blocks"] == []
    assert blank["gaps"][0]["code"] == "no_text_layer"
    digital = service.parse(service.register_bytes("digital.pdf", _pdf(True, pages=2))["id"], max_pages=1)
    assert digital["status"] == "partial"
    assert "Synthetic PDF fixture." in digital["blocks"][0]["exact_text"]
    assert digital["blocks"][0]["locator"]["page"] == 1
    assert digital["coverage"]["total_pages"] == 2
    assert digital["coverage"]["processed_pages"] == 1


def test_corrupt_original_not_silently_parsed(service):
    source = service.register_bytes("fixture.txt", b"original")
    (service.blob_dir / source["blob_sha256"]).write_bytes(b"tampered")
    with pytest.raises(SourceError, match="integrity"):
        service.parse(source["id"])
    with pytest.raises(SourceError, match="corrupted"):
        service.register_bytes("fixture.txt", b"original")


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "https://localhost/a", "http://127.0.0.1/", "http://[::1]/", "http://169.254.169.254/",
    "https://10.1.2.3/", "https://172.16.1.1/", "https://192.168.1.1/", "https://user:secret@example.org/",
    "https://example.org:8080/", "https://example.org\\@127.0.0.1/", "https://a.local/", "https://localhost./",
])
def test_remote_url_blocks_local_and_ambiguous_addresses(url):
    with pytest.raises(SourceError):
        validate_remote_url(url)


def test_dns_private_resolution_is_rejected_without_connecting(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 80))])
    with pytest.raises(SourceError, match="non-public"):
        fetch_public_url("https://example.org/a.md")


def test_redirect_is_revalidated_before_connection(monkeypatch):
    from sckg_workbench import sources
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))])
    calls = []
    class Redirect:
        status = 302
        def getheader(self, name, default=None):
            return "http://127.0.0.1/private" if name == "Location" else default
    class FakeConnection:
        def __init__(self, host, address, timeout):
            calls.append((host, address))
        def request(self, *a, **kw): pass
        def getresponse(self): return Redirect()
        def close(self): pass
    monkeypatch.setattr(sources, "_PinnedHTTPSConnection", FakeConnection)
    with pytest.raises(SourceError, match="Non-public"):
        fetch_public_url("https://example.org/a.md")
    assert calls == [("example.org", "93.184.216.34")]


def test_remote_requires_opt_in_and_idempotency_avoids_refetch(service):
    calls = []
    def fixture_fetcher(url, **limits):
        calls.append((url, limits))
        return FetchResult(b"<p>Synthetic web fixture.</p>", url, "text/html; charset=utf-8")
    with pytest.raises(SourceError, match="explicit"):
        service.register_url("https://example.org/tutorial", fetcher=fixture_fetcher)
    assert not calls
    first = service.register_url("https://example.org/tutorial", allow_network=True, fetcher=fixture_fetcher, request_id="remote-1")
    assert first == service.register_url("https://example.org/tutorial", allow_network=True, fetcher=fixture_fetcher, request_id="remote-1")
    assert len(calls) == 1
    assert first["filename"] == "tutorial.html"
    assert service.parse(first["id"])["status"] == "complete"


def test_injected_fetcher_cannot_report_private_redirect_target(service):
    with pytest.raises(SourceError, match="Non-public"):
        service.register_url("https://example.org/", allow_network=True, fetcher=lambda *a, **kw: FetchResult(b"fixture", "http://127.0.0.1/private"))
    assert not service.ledger.list_records("source")


def test_github_requires_commit_and_exact_path_and_never_executes(service):
    commit = "a" * 40
    assert github_raw_url("owner/repo", commit, "docs/test.md") == f"https://raw.githubusercontent.com/owner/repo/{commit}/docs/test.md"
    with pytest.raises(SourceError, match="commit"):
        github_raw_url("owner/repo", "main", "README.md")
    with pytest.raises(SourceError):
        github_raw_url("owner/repo", commit, "../README.md")
    source = service.register_github("owner/repo", commit, "README.md", allow_network=True,
        fetcher=lambda url, **kw: FetchResult(b"# Synthetic repository document", url, "text/plain"))
    assert source["metadata"]["commit"] == commit
    assert source["trust_status"] == "unreviewed"
    assert service.parse(source["id"])["status"] == "complete"


def test_unsupported_and_malformed_documents_report_gap(service):
    for name, data in [("data.bin", b"opaque"), ("corrupt.pdf", b"not a PDF"), ("bad.txt", b"\xff\xfe")]:
        ir = service.parse(service.register_bytes(name, data)["id"])
        assert ir["status"] == "parse_gap"
        assert not ir["blocks"]


def test_docx_duplicate_members_rejected(service):
    output = io.BytesIO()
    with pytest.warns(UserWarning), zipfile.ZipFile(output, "w") as archive:
        archive.writestr("word/document.xml", "<document><body /></document>")
        archive.writestr("word/document.xml", "<document><body /></document>")
    ir = service.parse(service.register_bytes("bad.docx", output.getvalue())["id"])
    assert ir["status"] == "parse_gap"
    assert "duplicate" in ir["gaps"][0]["detail"]


def test_docx_expansion_limit_fails_before_parsing(service):
    xml = "<document><body><p>" + "a" * 2000000 + "</p></body></document>"
    ir = service.parse(service.register_bytes("compressed.docx", _docx(xml))["id"])
    assert ir["status"] == "parse_gap"
    assert "expansion limits" in ir["gaps"][0]["detail"]


def test_github_redirect_does_not_masquerade_as_pinned_revision(service):
    with pytest.raises(SourceError, match="immutable commit/path"):
        service.register_github("owner/repo", "a" * 40, "README.md", allow_network=True,
            fetcher=lambda url, **kw: FetchResult(b"unrelated", "https://example.org/README.md"))
    assert not service.ledger.list_records("source")


@pytest.mark.parametrize("content_length,body", [(None, b"oversized"), ("1000", b"tiny")])
def test_default_fetcher_enforces_size_limit_without_network(monkeypatch, content_length, body):
    from sckg_workbench import sources
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))])
    class Response:
        status = 200
        def __init__(self): self.buffer = io.BytesIO(body)
        def getheader(self, name, default=None):
            return content_length if name == "Content-Length" else default
        def read1(self, count): return self.buffer.read(count)
    class Connection:
        sock = None
        def __init__(self, *a): pass
        def request(self, *a, **kw): pass
        def getresponse(self): return Response()
        def close(self): pass
    monkeypatch.setattr(sources, "_PinnedHTTPSConnection", Connection)
    with pytest.raises(SourceError, match="size limit|oversized"):
        fetch_public_url("https://example.org/fixture.md", max_bytes=4)


def test_public_connection_uses_validated_ip_not_a_second_hostname_lookup(monkeypatch):
    from sckg_workbench.sources import _PinnedHTTPConnection
    calls = []
    sentinel = object()
    def connect(address, timeout):
        calls.append((address, timeout))
        return sentinel
    monkeypatch.setattr(socket, "create_connection", connect)
    connection = _PinnedHTTPConnection("example.org", "93.184.216.34", 5)
    connection.connect()
    assert calls == [(("93.184.216.34", 80), 5)]
    assert connection.sock is sentinel
