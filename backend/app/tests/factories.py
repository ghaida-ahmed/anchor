"""Builders for test documents."""

import io

from pypdf import PdfWriter


def make_text_pdf(pages: list[str]) -> bytes:
    """Minimal hand-built PDF with a real, extractable text layer per page."""
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    font_id = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    page_ids: list[int] = []
    content_ids: list[int] = []
    for text in pages:
        escaped = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        lines = escaped.split("\n")
        # One Tj per line, moved down 14pt each, inside a single BT/ET block.
        drawn = "\n".join(f"({line}) Tj 0 -14 Td" for line in lines)
        stream = f"BT /F1 11 Tf 40 740 Td\n{drawn}\nET".encode("latin-1", "replace")
        content_ids.append(
            add(
                b"<< /Length "
                + str(len(stream)).encode()
                + b" >>\nstream\n"
                + stream
                + b"\nendstream"
            )
        )
        page_ids.append(0)  # placeholder, filled below

    pages_id = len(objects) + len(pages) + 1

    for position, content_id in enumerate(content_ids):
        page_ids[position] = add(
            b"<< /Type /Page /Parent " + str(pages_id).encode() + b" R "
            b"/MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 " + str(font_id).encode() + b" 0 R >> >> "
            b"/Contents " + str(content_id).encode() + b" 0 R >>"
        )

    kids = b" ".join(f"{pid} 0 R".encode() for pid in page_ids)
    actual_pages_id = add(
        b"<< /Type /Pages /Kids ["
        + kids
        + b"] /Count "
        + str(len(pages)).encode()
        + b" >>"
    )
    catalog_id = add(
        b"<< /Type /Catalog /Pages " + str(actual_pages_id).encode() + b" 0 R >>"
    )

    # Fix up the /Parent references now that the Pages object id is known.
    for pid in page_ids:
        objects[pid - 1] = objects[pid - 1].replace(
            b"/Parent " + str(pages_id).encode() + b" R",
            b"/Parent " + str(actual_pages_id).encode() + b" 0 R",
        )

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"

    xref_offset = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode()

    return bytes(out)


def make_image_only_pdf() -> bytes:
    """A structurally valid PDF with no text layer — what a scan looks like."""
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()
