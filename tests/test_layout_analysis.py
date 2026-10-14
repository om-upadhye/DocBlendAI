"""Layout analysis (regions, tables, reading order, spacing), table-aware chunking, and exports."""

import csv
import io
import json
import zipfile

import pytest
from PIL import Image

from tests.conftest import TYPED_PAGE

from app.models.schemas import ContentType, RecognizedChunk
from app.modules import chunker, content_type, exporters, layout_analysis, ocr_extractor, vector_store

PAGE = Image.new("L", (1000, 1400), 255)


def _line(text, box, words=None, conf=0.9):
    line = {"text": text, "box": box, "conf": conf}
    if words:
        line["words"] = [{"text": t, "box": b, "conf": conf} for t, b in words]
    return line


def _region(kind, box, score=0.9):
    return {"type": kind, "box": box, "score": score}


# A table: header + 2 rows, three columns at x = 0.10 / 0.40 / 0.70.
TABLE_LINES = [
    _line(f"{a} {b} {c}", [0.10, y, 0.80, y + 0.02], [(a, [0.10, y, 0.20, y + 0.02]), (b, [0.40, y, 0.48, y + 0.02]), (c, [0.70, y, 0.80, y + 0.02])])
    for (a, b, c), y in [(("Name", "DSA", "Total"), 0.40), (("Asha", "91", "258"), 0.43), (("Ravi", "75", "247"), 0.46)]
]


# --- pure functions -------------------------------------------------------------------------


def test_dedupe_keeps_the_more_specific_region() -> None:
    kept = layout_analysis.dedupe([_region("text", [0.1, 0.5, 0.6, 0.55], 0.95), _region("caption", [0.1, 0.5, 0.6, 0.55], 0.6)])
    assert [r["type"] for r in kept] == ["caption"]


def test_reading_order_left_column_before_right_and_header_footer_at_the_ends() -> None:
    regions = [
        _region("footer", [0.4, 0.95, 0.6, 0.97]),
        _region("text", [0.55, 0.20, 0.95, 0.40]),  # right column, top
        _region("text", [0.05, 0.50, 0.45, 0.70]),  # left column, lower
        _region("title", [0.05, 0.10, 0.95, 0.15]),  # full width
        _region("header", [0.05, 0.02, 0.4, 0.04]),
        _region("text", [0.05, 0.20, 0.45, 0.40]),  # left column, top
    ]
    order = [(r["type"], r["box"][0], r["box"][1]) for r in layout_analysis.reading_order(regions)]
    assert order == [
        ("header", 0.05, 0.02), ("title", 0.05, 0.10),
        ("text", 0.05, 0.20), ("text", 0.05, 0.50), ("text", 0.55, 0.20),
        ("footer", 0.4, 0.95),
    ]


def test_parse_table_html_expands_colspan() -> None:
    html = "<table><tr><td colspan=2>Marks</td><td>Total</td></tr><tr><td>91</td><td>88</td><td>179</td></tr></table>"
    assert layout_analysis.parse_table_html(html) == [["Marks", "", "Total"], ["91", "88", "179"]]


def test_rows_from_alignment_splits_cells_at_wide_gaps() -> None:
    assert layout_analysis.rows_from_alignment(TABLE_LINES) == [["Name", "DSA", "Total"], ["Asha", "91", "258"], ["Ravi", "75", "247"]]


def test_layout_text_keeps_columns_and_indentation() -> None:
    text = layout_analysis.layout_text(TABLE_LINES + [_line("  indented note", [0.30, 0.52, 0.60, 0.54])])
    rows = text.splitlines()
    assert rows[0].index("DSA") == rows[1].index("91") == rows[2].index("75")
    assert rows[0].index("Total") == rows[1].index("258")
    assert rows[-1].startswith(" ") and rows[-1].strip() == "indented note"


def test_analyze_page_builds_regions_tables_and_reading_order(fake_layout) -> None:
    fake_layout.regions = [_region("table", [0.08, 0.38, 0.85, 0.49]), _region("text", [0.08, 0.20, 0.85, 0.30])]
    lines = [
        _line("Semester Results", [0.10, 0.05, 0.60, 0.10]),  # big line no region covers -> title
        _line("The table lists the marks.", [0.10, 0.22, 0.60, 0.24]),
        *TABLE_LINES,
    ]
    result = layout_analysis.analyze_page(PAGE, lines)

    assert [r["type"] for r in result["regions"]] == ["title", "text", "table"]
    table = result["regions"][2]
    assert table["rows"] == [["Name", "DSA", "Total"], ["Asha", "91", "258"], ["Ravi", "75", "247"]]
    assert result["text"].split("\n\n") == ["Semester Results", "The table lists the marks.", "Name  DSA  Total\nAsha  91  258\nRavi  75  247"]
    assert layout_analysis.qa_blocks(result["regions"])[2] == (table["text"], ContentType.TABLE)


def test_analyze_page_without_a_layout_model_still_groups_lines(fake_layout, monkeypatch) -> None:
    def _missing(image):
        raise layout_analysis.LayoutUnavailableError("no model")

    monkeypatch.setattr(layout_analysis, "detect", _missing)
    result = layout_analysis.analyze_page(PAGE, [_line("Just one line", [0.1, 0.1, 0.5, 0.12])])
    assert [(r["type"], r["text"]) for r in result["regions"]] == [("text", "Just one line")]


# --- chunking ---------------------------------------------------------------------------------


def test_chunker_keeps_tables_as_their_own_chunks() -> None:
    blocks = [("Intro paragraph.", None), ("Name  DSA\nAsha  91", ContentType.TABLE), ("Closing words.", None)]
    chunks = chunker.chunk_pages("d", [("ignored when blocks are given", 0.8)], blocks=[blocks])
    assert [(c.text, c.content_type) for c in chunks] == [
        ("Intro paragraph.", ContentType.PARAGRAPH),
        ("Name  DSA\nAsha  91", ContentType.TABLE),
        ("Closing words.", ContentType.PARAGRAPH),
    ]
    assert all(c.raw_conf == 0.8 for c in chunks)


def test_long_tables_split_between_rows_repeating_the_header() -> None:
    rows = ["Name  Marks"] + [f"Student{i:02d}  {50 + i}" for i in range(40)]
    chunks = chunker.chunk_pages("d", [("", 1.0)], chunk_size=200, overlap=50, blocks=[[("\n".join(rows), ContentType.TABLE)]])
    assert len(chunks) > 1
    assert all(c.text.startswith("Name  Marks\n") and c.content_type is ContentType.TABLE for c in chunks)
    assert sum(c.text.count("Student") for c in chunks) == 40


def test_label_chunks_keeps_a_table_label_from_layout_analysis() -> None:
    chunk = RecognizedChunk(chunk_id="x", text="plain words that look like prose.", content_type=ContentType.TABLE, raw_conf=1.0)
    assert content_type.label_chunks([chunk])[0].content_type is ContentType.TABLE


# --- upload -> pages -> exports -------------------------------------------------------------


@pytest.fixture
def scanned_table_page(monkeypatch, fake_layout):
    """OCR returns a title, a sentence, and a 3x3 table with word boxes; layout finds the table."""
    lines = [_line("Semester Results", [0.10, 0.05, 0.60, 0.10]), _line("The table lists the marks.", [0.10, 0.22, 0.60, 0.24]), *TABLE_LINES]

    def _ocr_image(image, lines_out=None):
        if lines_out is not None:
            lines_out.extend(json.loads(json.dumps(lines)))
        return "\n".join(l["text"] for l in lines), 0.9

    monkeypatch.setattr(ocr_extractor, "ocr_image", _ocr_image)
    fake_layout.regions = [_region("table", [0.08, 0.38, 0.85, 0.49])]


def _upload_scan(client, pdf_file):
    with pdf_file([""]).open("rb") as f:
        resp = client.post("/upload", files={"file": ("marks.pdf", f, "application/pdf")}, data={"format_hint": "scanned"})
    assert resp.status_code == 201, resp.text
    return resp.json()["doc_id"]


def test_scanned_upload_saves_regions_and_table_chunks(client, pdf_file, scanned_table_page) -> None:
    doc_id = _upload_scan(client, pdf_file)

    [page] = client.get(f"/documents/{doc_id}/pages").json()
    assert [r["type"] for r in page["regions"]] == ["title", "text", "table"]
    assert page["regions"][2]["rows"][1] == ["Asha", "91", "258"]
    assert page["layout_text"].splitlines()[-3].startswith("Name")
    assert page["text"].startswith("Semester Results\n\nThe table lists the marks.")

    chunks = vector_store.get_chunks([f"{doc_id}:{i}" for i in range(5)])
    tables = [c for c in chunks.values() if c.content_type is ContentType.TABLE]
    assert len(tables) == 1 and tables[0].text == "Name  DSA  Total\nAsha  91  258\nRavi  75  247"


def test_exports(client, pdf_file, scanned_table_page) -> None:
    doc_id = _upload_scan(client, pdf_file)
    get = lambda fmt: client.get(f"/documents/{doc_id}/export", params={"format": fmt})  # noqa: E731

    layout = get("layout")
    assert layout.status_code == 200 and 'filename="marks_layout.txt"' in layout.headers["content-disposition"]
    assert "Asha" in layout.text

    md = get("md").text
    assert "### Semester Results" in md and "| Name | DSA | Total |" in md and "| Asha | 91 | 258 |" in md

    table_csv = get("csv")
    assert table_csv.headers["content-type"].startswith("text/csv")
    assert list(csv.reader(io.StringIO(table_csv.content.decode("utf-8-sig"))))[2] == ["Ravi", "75", "247"]

    data = get("json").json()
    assert data["doc_id"] == doc_id and data["name"] == "marks.pdf" and "file_path" not in data
    assert data["pages"][0]["regions"][2]["type"] == "table"
    assert get("txt").text.startswith("Semester Results")
    assert get("pdf").status_code == 422
    assert client.get("/documents/nope/export").status_code == 404


def test_csv_export_zips_several_tables_and_404s_without_any() -> None:
    pages = [{"page": 1, "regions": [{"type": "table", "rows": [["a"]]}], "blocks": []},
             {"page": 2, "regions": [], "blocks": [{"type": "table", "rows": [["b"]]}]}]
    content, media_type, ext = exporters.to_csv(pages)
    assert (media_type, ext) == ("application/zip", "zip")
    assert sorted(zipfile.ZipFile(io.BytesIO(content)).namelist()) == ["page1_table1.csv", "page2_table1.csv"]
    with pytest.raises(exporters.ExportError):
        exporters.to_csv([{"page": 1, "text": "no tables"}])


def test_typed_pdf_has_spacing_preserving_layout_text(client, pdf_file) -> None:
    with pdf_file([TYPED_PAGE + "\nName      Marks\nAsha      91"]).open("rb") as f:
        doc_id = client.post("/upload", files={"file": ("t.pdf", f, "application/pdf")}).json()["doc_id"]
    [page] = client.get(f"/documents/{doc_id}/pages").json()
    assert "Asha" in page["layout_text"] and page["regions"] == []


def test_tables_are_read_again_and_replace_the_page_ocr_there(fake_layout) -> None:
    fake_layout.regions = [_region("table", [0.08, 0.38, 0.85, 0.49])]
    fake_layout.reread = json.loads(json.dumps(TABLE_LINES))
    broken = _line("ame 9", [0.10, 0.43, 0.30, 0.45])  # what the page OCR made of the table
    result = layout_analysis.analyze_page(PAGE, [_line("Intro sentence.", [0.1, 0.1, 0.5, 0.12]), broken])

    assert [r["type"] for r in result["regions"]] == ["text", "table"]
    assert result["regions"][1]["rows"][2] == ["Ravi", "75", "247"]
    assert [l["text"] for l in result["lines"]] == ["Intro sentence.", "Name DSA Total", "Asha 91 258", "Ravi 75 247"]
    assert "Asha  91  258" in result["text"] and "ame 9" not in result["text"]


def test_parse_table_html_keeps_columns_under_a_rowspan() -> None:
    html = ("<table><tr><td rowspan=2>Criteria</td><td colspan=2>Languages</td></tr>"
            "<tr><td>C++</td><td>Java</td></tr><tr><td>Keywords</td><td>62</td><td>50</td></tr></table>")
    assert layout_analysis.parse_table_html(html) == [["Criteria", "Languages", ""], ["", "C++", "Java"], ["Keywords", "62", "50"]]


def _ruled_table() -> tuple[Image.Image, list[dict]]:
    """A drawn 3-column table: merged header cell, a rowspan cell, and a two-line cell."""
    from PIL import ImageDraw

    img = Image.new("L", (900, 700), 255)
    d = ImageDraw.Draw(img)
    X, Y = [100, 350, 600, 850], [100, 180, 260, 340, 500]
    for y in Y:
        d.line([X[0], y, X[-1], y], fill=0, width=3)
    for x in X:
        d.line([x, Y[0], x, Y[-1]], fill=0, width=3)
    d.line([X[1], Y[0], X[-1], Y[0]], fill=0, width=3)
    d.rectangle([X[2] - 3, Y[0] + 3, X[2] + 3, Y[1] - 3], fill=255)  # "Languages" spans columns 2-3
    d.rectangle([X[0] + 3, Y[1] - 3, X[1] - 3, Y[1] + 3], fill=255)  # "Criteria" spans rows 1-2
    W, H = img.size

    def piece(text, x0, y0, x1, y1):
        return _line(text, [x0 / W, y0 / H, x1 / W, y1 / H], [(text, [x0 / W, y0 / H, x1 / W, y1 / H])])

    lines = [piece("Criteria", 120, 120, 220, 150), piece("Languages", 400, 120, 560, 150),
             piece("C++", 370, 200, 420, 230), piece("Java", 620, 200, 690, 230),
             piece("Keywords", 120, 280, 240, 310), piece("62", 370, 280, 400, 310), piece("50", 620, 280, 650, 310),
             piece("Struct", 120, 360, 200, 390), piece("Reference typed", 370, 360, 560, 390),
             piece("with access", 370, 420, 520, 450), piece("No", 620, 360, 660, 390)]
    return img, lines


def test_grid_rows_reads_merged_and_multi_line_cells_from_the_rules() -> None:
    img, lines = _ruled_table()
    assert layout_analysis.grid_rows(img, [100 / 900, 100 / 700, 850 / 900, 500 / 700], lines) == [
        ["Criteria", "Languages", ""],
        ["", "C++", "Java"],
        ["Keywords", "62", "50"],
        ["Struct", "Reference typed with access", "No"],
    ]


def test_grid_rows_is_none_for_tables_without_rules() -> None:
    assert layout_analysis.grid_rows(PAGE, [0.08, 0.38, 0.85, 0.49], TABLE_LINES) is None
