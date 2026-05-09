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
    # JPEG 2000: JP2 file signature or raw codestream signature
    (0, b"\x00\x00\x00\x0cjP  \r\n\x87\n", {"jp2"}),
    (0, b"\xffO\xffQ", {"jp2"}),
    # TIFF: little-endian or big-endian header
    (0, b"II*\x00", {"tiff"}),
    (0, b"MM\x00*", {"tiff"}),
    # ZIP-based formats (DOCX, PPTX, XLSX are ZIP archives)
    # PK\x03\x04 = ZIP local file header
    (0, b"PK\x03\x04", {"docx", "pptx", "xlsx"}),
]


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

    # If no signature matched, reject it for the supported upload set.
    if not matched_extensions:
        logger.warning("No magic signature matched", ext=claimed_extension)
        return False

    # The claimed extension must be in the matched set
    if claimed_extension in matched_extensions:
        return True

    # Special: ZIP-based formats (docx/pptx/xlsx) all share PK signature.
    # We can't distinguish between them via magic bytes alone, so allow all
    # supported ZIP-based Office extensions if the file is a ZIP.
    zip_extensions = {"docx", "pptx", "xlsx"}
    if claimed_extension in zip_extensions and matched_extensions & zip_extensions:
        return True

    logger.warning(
        "Magic bytes mismatch",
        claimed_ext=claimed_extension,
        detected_exts=matched_extensions,
    )
    return False
