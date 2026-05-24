"""Resume text extraction and section splitting.

Supports PDF (via PyMuPDF/fitz), DOCX (via python-docx), and plain text.
Heuristically splits extracted text into canonical resume sections:
    summary, experience, skills, education, other.

PII discipline (CLAUDE.md §8 rule 6): candidate names, email addresses,
and phone numbers must never appear in log output. Section character-count
metadata is logged instead of text content.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger(__name__)

# ── Section keyword map ────────────────────────────────────────────────────────

_SECTION_KEYWORDS: dict[str, list[str]] = {
    "summary": [
        "summary", "profile", "objective", "about", "overview",
        "professional summary", "executive summary",
    ],
    "experience": [
        "experience", "work experience", "employment", "career",
        "work history", "professional experience", "positions held",
    ],
    "skills": [
        "skills", "technical skills", "competencies", "expertise",
        "technologies", "tools", "key skills", "core competencies",
    ],
    "education": [
        "education", "academic", "qualifications", "degrees",
        "academic background", "training", "certifications",
    ],
}

# Build a reverse lookup: keyword → canonical section name
_KEYWORD_TO_SECTION: dict[str, str] = {
    kw: section
    for section, keywords in _SECTION_KEYWORDS.items()
    for kw in keywords
}

# A header line: ≤ 60 chars, optional trailing colon/whitespace, matches a keyword
_HEADER_RE = re.compile(
    r"^\s*(" + "|".join(re.escape(kw) for kw in sorted(_KEYWORD_TO_SECTION, key=len, reverse=True)) + r")\s*:?\s*$",
    re.IGNORECASE,
)

# PII patterns used exclusively for log-output sanitisation
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.\w+\b")
_PHONE_RE = re.compile(r"\b(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class ParsedResume:
    """Extracted text and heuristic section map for a single resume.

    Attributes:
        candidate_uuid: UUID of the candidate (no PII).
        file_ext: Source format: "pdf", "docx", or "txt".
        full_text: Complete extracted UTF-8 text.
        sections: Dict mapping section name to its text body.
            Keys: "summary", "experience", "skills", "education", "other".
            Any section absent from the document has an empty string value.
    """

    candidate_uuid: str
    file_ext: str
    full_text: str
    sections: dict[str, str] = field(default_factory=lambda: {
        "summary": "", "experience": "", "skills": "", "education": "", "other": "",
    })


# ── Public API ─────────────────────────────────────────────────────────────────

def parse_resume(
    candidate_uuid: str,
    file_ext: str,
    data: bytes,
) -> ParsedResume:
    """Extract and section-split a resume document.

    Args:
        candidate_uuid: UUID of the candidate (no PII — used only in logs).
        file_ext: File extension without leading dot: "pdf", "docx", or "txt".
        data: Raw file bytes.

    Returns:
        ParsedResume with full_text and sections populated.

    Raises:
        ValueError: For unrecognised file_ext.
        RuntimeError: If the underlying parser library is not installed.
    """
    ext = file_ext.lower().lstrip(".")

    if ext == "pdf":
        text = _extract_pdf(data)
    elif ext == "docx":
        text = _extract_docx(data)
    elif ext == "txt":
        text = data.decode("utf-8", errors="replace")
    else:
        raise ValueError(
            f"Unsupported file extension '{ext}'. Accepted: pdf, docx, txt."
        )

    sections = split_sections(text)

    _log_parse_result(candidate_uuid, ext, text, sections)
    return ParsedResume(
        candidate_uuid=candidate_uuid,
        file_ext=ext,
        full_text=text,
        sections=sections,
    )


def split_sections(text: str) -> dict[str, str]:
    """Heuristically split resume text into canonical sections.

    Identifies section headers by matching against the keyword map and
    assigns following lines to that section until the next header.
    Unmatched content accumulates under the "other" key.

    Args:
        text: Full extracted resume text (UTF-8).

    Returns:
        Dict with keys: summary, experience, skills, education, other.
        All values are non-None strings (empty if the section is absent).
    """
    sections: dict[str, list[str]] = {
        "summary": [], "experience": [], "skills": [], "education": [], "other": [],
    }
    current: str = "other"

    for line in text.splitlines():
        m = _HEADER_RE.match(line)
        if m:
            matched_kw = m.group(1).lower()
            current = _KEYWORD_TO_SECTION.get(matched_kw, "other")
        else:
            sections[current].append(line)

    return {k: "\n".join(v).strip() for k, v in sections.items()}


# ── Format-specific extractors ─────────────────────────────────────────────────

def _extract_pdf(data: bytes) -> str:
    """Extract text from a PDF using PyMuPDF (fitz).

    Args:
        data: Raw PDF bytes.

    Returns:
        Concatenated page text separated by newlines.

    Raises:
        RuntimeError: If PyMuPDF is not installed.
    """
    try:
        import fitz  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError(
            "PyMuPDF is required for PDF parsing. Install with: pip install PyMuPDF"
        ) from exc

    with fitz.open(stream=data, filetype="pdf") as doc:
        pages = [page.get_text("text") for page in doc]
    return "\n".join(pages)


def _extract_docx(data: bytes) -> str:
    """Extract text from a DOCX using python-docx.

    Args:
        data: Raw DOCX bytes.

    Returns:
        Paragraph text joined with newlines.

    Raises:
        RuntimeError: If python-docx is not installed.
    """
    import io

    try:
        from docx import Document  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError(
            "python-docx is required for DOCX parsing. Install with: pip install python-docx"
        ) from exc

    doc = Document(io.BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs)


# ── Logging helper ─────────────────────────────────────────────────────────────

def _log_parse_result(
    candidate_uuid: str,
    file_ext: str,
    text: str,
    sections: dict[str, str],
) -> None:
    """Log parse metadata — never log text content (PII risk)."""
    # Verify the extracted text itself contains no email/phone in logs
    # by logging only character counts per section, not content.
    section_char_counts = {k: len(v) for k, v in sections.items() if v}
    logger.info(
        "resume_parsed",
        candidate_uuid=candidate_uuid,   # UUID — no PII
        file_ext=file_ext,
        total_chars=len(text),
        sections_found=list(section_char_counts.keys()),
        section_char_counts=section_char_counts,
    )
