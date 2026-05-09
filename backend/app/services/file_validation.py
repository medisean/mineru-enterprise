"""
File type validation via magic bytes (file signatures).

Validates that uploaded files match their claimed extension by inspecting
the first few bytes of the file content, rather than trusting the filename alone.
"""
import structlog

logger = structlog.get_logger(__name__)

# Magic bytes signatures for supported file types.
# Each entry: (offset, byte_pattern, set_of_valid_extensions)
# Most signatures are at offset 0.
MAGIC_SIGNATURES: list[tuple[int, bytes, set[str]]] = [
    # PDF: %PDF-
    (0, b"%PDF", {"pdf"}),
    # PNG: 89 50 4E 47
    (0, b"\x89PNG", {"png"}),
    # JPEG: FF D8 FF
    (0, b"\xff\xd8\xff", {"jpg", "jpeg"}),
    # GIF: GIF87a or GIF89a
    (0, b"GIF8", {"gif"}),
    # BMP: BM
    (0, b"BM", {"bmp"}),
    # WebP: RIFF....WEBP
    (0, b"RIFF", {"webp"}),  # WebP starts with RIFF, we check WEBP at offset 8 below
    # ZIP-based formats (DOCX, PPTX, XLSX are ZIP archives)
    # PK\x03\x04 = ZIP local file header
    (0, b"PK\x03\x04", {"docx", "pptx", "xlsx", "doc", "ppt", "xls"}),
    # Microsoft Compound File Binary Format (legacy .doc, .ppt, .xls)
    # D0 CF 11 E0 A1 B1 1A E1
    (0, b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", {"doc", "ppt", "xls"}),
    # JPEG 2000: 00 00 00 0C 6A 50 20 20
    (0, b"\x00\x00\x00\x0c\x6a\x50", {"jp2"}),
    # HTML: starts with <! or <html or <?xml (loose check)
    # Note: HTML is text-based, so we just check it starts with '<' after optional whitespace
]

# Extensions that are text-based and cannot be reliably validated by magic bytes.
TEXT_EXTENSIONS = {"html", "htm"}


def validate_file_magic(head_bytes: bytes, claimed_extension: str) -> bool:
    """Validate that the file's magic bytes match its claimed extension.

    Args:
        head_bytes: The first ~32 bytes of the file content.
        claimed_extension: The file extension (lowercase, no dot) from the filename.

    Returns:
        True if the magic bytes are consistent with the extension (or if the
        extension has no known signature, in which case we allow it).
    """
    if not head_bytes:
        logger.warning("Empty head bytes, skipping magic validation", ext=claimed_extension)
        return True

    # Text-based formats: just check it looks like text
    if claimed_extension in TEXT_EXTENSIONS:
        # HTML files are text; accept if content starts with '<' (after trimming whitespace)
        stripped = head_bytes.lstrip()
        if stripped and stripped[0:1] == b"<":
            return True
        # Also accept if it's valid UTF-8 text
        try:
            head_bytes.decode("utf-8")
            return True
        except UnicodeDecodeError:
            return False

    # Check known magic signatures
    matched_extensions: set[str] = set()
    for offset, pattern, extensions in MAGIC_SIGNATURES:
        end = offset + len(pattern)
        if len(head_bytes) >= end and head_bytes[offset:end] == pattern:
            matched_extensions.update(extensions)

    # Special case: WebP needs RIFF at 0 AND WEBP at 8
    if b"RIFF" in head_bytes[:4] and len(head_bytes) >= 12:
        if head_bytes[8:12] == b"WEBP":
            matched_extensions.add("webp")

    # If no signature matched, we can't validate — allow it (conservative)
    if not matched_extensions:
        logger.info("No magic signature matched, allowing by default", ext=claimed_extension)
        return True

    # The claimed extension must be in the matched set
    if claimed_extension in matched_extensions:
        return True

    # Special: ZIP-based formats (docx/pptx/xlsx) all share PK signature.
    # We can't distinguish between them via magic bytes alone, so allow all
    # ZIP-based extensions if the file is a ZIP.
    zip_extensions = {"docx", "pptx", "xlsx", "doc", "ppt", "xls"}
    if claimed_extension in zip_extensions and matched_extensions & zip_extensions:
        return True

    logger.warning(
        "Magic bytes mismatch",
        claimed_ext=claimed_extension,
        detected_exts=matched_extensions,
    )
    return False
