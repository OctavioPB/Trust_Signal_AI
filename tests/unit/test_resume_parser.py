"""Unit tests for ingestion/resume_parser.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ingestion.resume_parser import (
    ParsedResume,
    _log_parse_result,
    parse_resume,
    split_sections,
)


# ── split_sections ─────────────────────────────────────────────────────────────

def test_split_sections_all_canonical_keys():
    """Result always contains all 5 canonical section keys."""
    sections = split_sections("")
    assert set(sections) == {"summary", "experience", "skills", "education", "other"}


def test_split_sections_empty_text():
    """All sections are empty strings for empty input."""
    sections = split_sections("")
    assert all(v == "" for v in sections.values())


def test_split_sections_unknown_content_goes_to_other():
    """Lines before the first header accumulate in 'other'."""
    text = "John Doe\nSenior Engineer"
    sections = split_sections(text)
    assert "John Doe" in sections["other"]
    assert "Senior Engineer" in sections["other"]


def test_split_sections_experience_header():
    """'Experience' header routes following lines to experience section."""
    text = "Experience\nBuilt distributed systems\nManaged cloud migration"
    sections = split_sections(text)
    assert "Built distributed systems" in sections["experience"]
    assert "Managed cloud migration" in sections["experience"]


def test_split_sections_case_insensitive_header():
    """Section headers are matched case-insensitively."""
    text = "SKILLS\nPython\nJava"
    sections = split_sections(text)
    assert "Python" in sections["skills"]
    assert "Java" in sections["skills"]


def test_split_sections_header_with_trailing_colon():
    """Headers with a trailing colon are recognised."""
    text = "Education:\nBSc Computer Science"
    sections = split_sections(text)
    assert "BSc Computer Science" in sections["education"]


def test_split_sections_multiple_headers_partition_correctly():
    """Multiple headers partition text into distinct sections."""
    text = (
        "Summary\n"
        "Hardworking professional\n"
        "Experience\n"
        "Built a product\n"
        "Education\n"
        "BSc CS"
    )
    sections = split_sections(text)
    assert "Hardworking professional" in sections["summary"]
    assert "Built a product" in sections["experience"]
    assert "BSc CS" in sections["education"]
    assert sections["skills"].strip() == ""


def test_split_sections_content_not_in_wrong_section():
    """Content assigned to one section does not appear in others."""
    text = "Skills\nPython Django\nExperience\nBuilt APIs"
    sections = split_sections(text)
    assert "Python Django" not in sections["experience"]
    assert "Built APIs" not in sections["skills"]


def test_split_sections_synonym_header_summary():
    """Synonym 'Profile' is routed to the summary section."""
    text = "Profile\nPassionate engineer"
    sections = split_sections(text)
    assert "Passionate engineer" in sections["summary"]


def test_split_sections_synonym_header_experience():
    """Synonym 'Work History' routes to experience section."""
    text = "Work History\nCompany A 2020–2023"
    sections = split_sections(text)
    assert "Company A 2020–2023" in sections["experience"]


# ── parse_resume ───────────────────────────────────────────────────────────────

def test_parse_resume_txt_full_text():
    """TXT parse captures full text content."""
    data = b"Summary\nI am a developer\nSkills\nPython"
    result = parse_resume("uuid-001", "txt", data)
    assert "I am a developer" in result.full_text


def test_parse_resume_txt_sections_populated():
    """TXT parse populates the sections dict correctly."""
    data = b"Summary\nI am a developer\nSkills\nPython"
    result = parse_resume("uuid-001", "txt", data)
    assert "I am a developer" in result.sections["summary"]
    assert "Python" in result.sections["skills"]


def test_parse_resume_returns_parsed_resume():
    """Return type is ParsedResume."""
    result = parse_resume("uuid-002", "txt", b"Summary\nHello world")
    assert isinstance(result, ParsedResume)


def test_parse_resume_file_ext_normalised():
    """file_ext is lowercased and stored without leading dot."""
    result = parse_resume("uuid-003", "TXT", b"hello world summary")
    assert result.file_ext == "txt"


def test_parse_resume_candidate_uuid_preserved():
    """candidate_uuid in ParsedResume matches the input UUID."""
    result = parse_resume("uuid-abc-123", "txt", b"Summary\nHello world")
    assert result.candidate_uuid == "uuid-abc-123"


def test_parse_resume_unsupported_ext_raises_value_error():
    """Unsupported file extensions raise ValueError."""
    with pytest.raises(ValueError, match="Unsupported"):
        parse_resume("uuid-004", "xlsx", b"data")


def test_parse_resume_txt_dot_prefix_stripped():
    """Leading dot in file_ext is stripped before dispatch."""
    result = parse_resume("uuid-005", ".txt", b"Summary\nDot prefix")
    assert result.file_ext == "txt"


# ── PII safety ─────────────────────────────────────────────────────────────────

def test_log_parse_result_does_not_log_email():
    """_log_parse_result must not emit email addresses in any log argument."""
    pii_text = "Jane Smith jane.smith@example.com 555-867-5309"
    sections = {
        "summary": pii_text,
        "experience": "",
        "skills": "",
        "education": "",
        "other": "",
    }
    mock_logger = MagicMock()
    with patch("ingestion.resume_parser.logger", mock_logger):
        _log_parse_result("uuid-pii", "txt", pii_text, sections)

    assert mock_logger.info.called
    call_kwargs = mock_logger.info.call_args[1]
    log_str = str(call_kwargs)
    assert "jane.smith@example.com" not in log_str
    assert "555-867-5309" not in log_str


def test_log_parse_result_does_not_log_text_content():
    """_log_parse_result logs only char counts, not raw section text."""
    mock_logger = MagicMock()
    sections = {
        "summary": "Confidential candidate information",
        "experience": "",
        "skills": "",
        "education": "",
        "other": "",
    }
    with patch("ingestion.resume_parser.logger", mock_logger):
        _log_parse_result("uuid-content", "txt", "Confidential candidate information", sections)

    call_kwargs = mock_logger.info.call_args[1]
    log_str = str(call_kwargs)
    assert "Confidential candidate information" not in log_str


def test_log_parse_result_logs_char_counts():
    """_log_parse_result logs section character counts (not text)."""
    mock_logger = MagicMock()
    sections = {
        "summary": "twelve chars",  # 12 chars
        "experience": "",
        "skills": "",
        "education": "",
        "other": "",
    }
    with patch("ingestion.resume_parser.logger", mock_logger):
        _log_parse_result("uuid-counts", "txt", "twelve chars", sections)

    call_kwargs = mock_logger.info.call_args[1]
    section_char_counts = call_kwargs.get("section_char_counts", {})
    assert section_char_counts.get("summary") == 12
