"""Unit tests for ml/features/code_style.py."""

from __future__ import annotations

import pytest

from ml.features.code_style import (
    CodeFileStyleResult,
    CodeStyleFeatures,
    CodeStyleScorer,
    _BOILERPLATE_MAX_SUSPICION,
    _BOILERPLATE_MIN_SUSPICION,
    _COMMENT_MAX_SUSPICION,
    _COMMENT_MIN_SUSPICION,
    _NAMING_MAX_SUSPICION,
    _NAMING_MIN_SUSPICION,
    _boilerplate_ratio,
    _comment_density,
    _levenshtein,
    _normalise,
)


# ── _levenshtein ───────────────────────────────────────────────────────────────

def test_levenshtein_identical_strings():
    assert _levenshtein("hello", "hello") == 0


def test_levenshtein_empty_strings():
    assert _levenshtein("", "") == 0


def test_levenshtein_one_empty():
    assert _levenshtein("abc", "") == 3
    assert _levenshtein("", "abc") == 3


def test_levenshtein_single_substitution():
    assert _levenshtein("cat", "car") == 1


def test_levenshtein_single_insertion():
    assert _levenshtein("cat", "cats") == 1


def test_levenshtein_single_deletion():
    assert _levenshtein("cats", "cat") == 1


def test_levenshtein_multi_edits():
    assert _levenshtein("kitten", "sitting") == 3


def test_levenshtein_symmetric():
    assert _levenshtein("abc", "xyz") == _levenshtein("xyz", "abc")


# ── _comment_density ──────────────────────────────────────────────────────────

def test_comment_density_all_comments():
    content = "# comment\n# another\n# third"
    assert _comment_density(content) == pytest.approx(1.0)


def test_comment_density_no_comments():
    content = "x = 1\ny = 2\nz = x + y"
    assert _comment_density(content) == pytest.approx(0.0)


def test_comment_density_half():
    content = "# comment\nx = 1\n# another\ny = 2"
    assert _comment_density(content) == pytest.approx(0.5, abs=1e-6)


def test_comment_density_empty_file():
    assert _comment_density("") == pytest.approx(0.0)


def test_comment_density_blank_lines_skipped():
    """Blank lines are not counted in denominator."""
    content = "# comment\n\n\nx = 1"
    assert _comment_density(content) == pytest.approx(0.5, abs=1e-6)


def test_comment_density_cpp_style():
    content = "// header\nint x = 0;\n/* block */"
    assert _comment_density(content) == pytest.approx(2 / 3, abs=1e-6)


# ── _boilerplate_ratio ─────────────────────────────────────────────────────────

def test_boilerplate_ratio_shebang():
    content = "#!/usr/bin/env python3\nx = 1"
    ratio = _boilerplate_ratio(content)
    assert ratio > 0.0


def test_boilerplate_ratio_main_guard():
    content = 'if __name__ == "__main__":\n    main()\nx = 1'
    ratio = _boilerplate_ratio(content)
    assert ratio > 0.0


def test_boilerplate_ratio_no_boilerplate():
    content = "x = 1\ny = 2\ndef f():\n    return x + y"
    assert _boilerplate_ratio(content) == pytest.approx(0.0)


def test_boilerplate_ratio_empty():
    assert _boilerplate_ratio("") == pytest.approx(0.0)


def test_boilerplate_ratio_copyright():
    content = "# Copyright (c) 2024 ACME Corp\n# All rights reserved\nx = 1"
    ratio = _boilerplate_ratio(content)
    assert ratio >= 2 / 3


# ── _normalise ────────────────────────────────────────────────────────────────

def test_normalise_forward_at_max():
    assert _normalise(_COMMENT_MAX_SUSPICION, _COMMENT_MAX_SUSPICION, _COMMENT_MIN_SUSPICION, inverse=False) == pytest.approx(1.0)


def test_normalise_forward_at_min():
    assert _normalise(_COMMENT_MIN_SUSPICION, _COMMENT_MAX_SUSPICION, _COMMENT_MIN_SUSPICION, inverse=False) == pytest.approx(0.0)


def test_normalise_inverse_at_max_suspicion_bound():
    """Inverse: value ≤ max_susp → score 1.0."""
    assert _normalise(_NAMING_MAX_SUSPICION, _NAMING_MAX_SUSPICION, _NAMING_MIN_SUSPICION, inverse=True) == pytest.approx(1.0)


def test_normalise_inverse_at_min_suspicion_bound():
    assert _normalise(_NAMING_MIN_SUSPICION, _NAMING_MAX_SUSPICION, _NAMING_MIN_SUSPICION, inverse=True) == pytest.approx(0.0)


def test_normalise_degenerate_bounds_returns_zero():
    assert _normalise(0.5, 0.5, 0.5) == pytest.approx(0.0)


def test_normalise_clamped_above():
    assert _normalise(1.0, _COMMENT_MAX_SUSPICION, _COMMENT_MIN_SUSPICION, inverse=False) == pytest.approx(1.0)


def test_normalise_clamped_below():
    assert _normalise(0.0, _COMMENT_MAX_SUSPICION, _COMMENT_MIN_SUSPICION, inverse=False) == pytest.approx(0.0)


# ── CodeStyleScorer.score_file ─────────────────────────────────────────────────

def test_score_file_returns_dataclass():
    scorer = CodeStyleScorer()
    result = scorer.score_file("main.py", "x = 1\ny = 2\nz = 3")
    assert isinstance(result, CodeFileStyleResult)


def test_score_file_preserves_file_path():
    scorer = CodeStyleScorer()
    result = scorer.score_file("src/utils.py", "x = 1")
    assert result.file_path == "src/utils.py"


def test_score_file_suspicion_in_unit_interval():
    scorer = CodeStyleScorer()
    for content in [
        "# comment\nx = 1",
        "def foo():\n    pass",
        "#!/usr/bin/env python3\n" * 5 + "x = 1",
    ]:
        result = scorer.score_file("f.py", content)
        assert 0.0 <= result.suspicion_score <= 1.0


def test_score_file_high_comment_density_raises_suspicion():
    """Many comment lines → high comment density → higher suspicion."""
    scorer = CodeStyleScorer()
    # ~80 % comment lines
    heavy = "\n".join(["# comment"] * 8 + ["x = i"] * 2)
    light = "\n".join(["x = i"] * 8 + ["# comment"] * 2)

    heavy_result = scorer.score_file("f.py", heavy)
    light_result = scorer.score_file("f.py", light)

    assert heavy_result.comment_density > light_result.comment_density
    assert heavy_result.suspicion_score >= light_result.suspicion_score


def test_score_file_uniform_identifiers_raises_suspicion():
    """Identifiers that differ by one character → low Levenshtein → higher suspicion."""
    scorer = CodeStyleScorer(seed=0)

    # Very uniform: alpha1 alpha2 alpha3 ... (all 6 chars, differ by 1)
    uniform_code = "\n".join(
        [f"def alpha{chr(ord('a') + i)}(): pass" for i in range(20)]
    )
    # Very varied: short and long identifiers mixed
    varied_code = (
        "def x(): pass\n"
        "def initialize_database_connection(): pass\n"
        "def run(): pass\n"
        "def compute_weighted_average_score(): pass\n"
        "def go(): pass\n"
        "def transform_user_profile_metadata(): pass\n"
    ) * 5

    uniform_result = scorer.score_file("u.py", uniform_code)
    varied_result  = scorer.score_file("v.py", varied_code)

    assert uniform_result.avg_identifier_edit_distance <= varied_result.avg_identifier_edit_distance


def test_score_file_boilerplate_heavy_raises_suspicion():
    """Many boilerplate lines → higher suspicion."""
    scorer = CodeStyleScorer()
    bplate = "#!/usr/bin/env python3\n" + "# Copyright (c) 2024\n" * 10 + "x = 1\n"
    clean  = "x = 1\ny = 2\ndef f():\n    return x + y\n"

    r_bplate = scorer.score_file("b.py", bplate)
    r_clean  = scorer.score_file("c.py", clean)

    assert r_bplate.boilerplate_ratio > r_clean.boilerplate_ratio


# ── CodeStyleScorer.score_repo ─────────────────────────────────────────────────

def test_score_repo_empty_returns_zero():
    scorer = CodeStyleScorer()
    result = scorer.score_repo("uuid-empty", [])

    assert result.suspicion_score == pytest.approx(0.0)
    assert result.file_results == {}


def test_score_repo_blank_only_file_skipped():
    scorer = CodeStyleScorer()
    result = scorer.score_repo("uuid-blank", [("blank.py", "   \n\n  ")])

    assert result.suspicion_score == pytest.approx(0.0)
    assert result.file_results == {}


def test_score_repo_result_is_dataclass():
    scorer = CodeStyleScorer()
    result = scorer.score_repo("uuid-1", [("main.py", "x = 1\ny = 2")])
    assert isinstance(result, CodeStyleFeatures)


def test_score_repo_preserves_uuid():
    scorer = CodeStyleScorer()
    result = scorer.score_repo("my-uuid", [("f.py", "x = 1\ny = 2\nz = 3")])
    assert result.repo_uuid == "my-uuid"


def test_score_repo_file_results_populated():
    scorer = CodeStyleScorer()
    result = scorer.score_repo("uuid-fr", [("a.py", "x = 1\ny = 2")])
    assert "a.py" in result.file_results


def test_score_repo_suspicion_in_unit_interval():
    scorer = CodeStyleScorer()
    files = [("a.py", "x = 1\ny = 2"), ("b.py", "def foo():\n    pass\n    return 1")]
    result = scorer.score_repo("uuid-range", files)
    assert 0.0 <= result.suspicion_score <= 1.0


def test_score_repo_no_pii():
    scorer = CodeStyleScorer()
    result = scorer.score_repo("uuid-pii", [("f.py", "x = 1")])

    assert not hasattr(result, "author_name")
    assert not hasattr(result, "candidate_name")
