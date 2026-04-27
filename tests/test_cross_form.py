"""
Cross-form connectivity tests driven by the rules engine.

Why these tests exist
---------------------
Previous test runs only checked HTML structure (coordinates, images).  They
had *zero* coverage of JavaScript behaviour or cross-form data contracts.  The
gaps that slipped through:

  • T1 never handled  s7_20800 (Schedule 7 RRSP deduction)
  • Schedule 7 never wrote cra_s7_20800 to localStorage
  • T1 never handled  s5_30300 / s5_30400 (Schedule 5)
  • T1 never handled  s8_22200 (Schedule 8)
  • T1 never handled  t2209_40500 (T2209)
  • BC428 required manual "Sync from T1" click instead of auto-syncing

How the tests work
------------------
Every assertion is derived from CROSS_FORM_RULES / T1_EXPORTS in
app/form_rules.py.  Adding a new inter-form connection to the rules engine
automatically creates new test coverage — no editing of this file needed.

Test categories
---------------
1. Rules engine self-consistency     – sanity-checks the rules engine itself
2. Sub-form → T1: localStorage key   – verify the sub-form template WRITES the key
3. Sub-form → T1: URL param          – verify the sub-form template SENDS the param
4. T1 ← sub-form: URL param handled  – verify T1 template handles each inbound param
5. T1 ← sub-form: localStorage read  – verify T1 reads the key on load
6. T1 → sub-form: localStorage write – verify T1 template WRITES each exported key
7. T1 → sub-form: localStorage read  – verify each sub-form reads the T1 key
8. T1 line classification coverage   – every sub_form line has a matching rule
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Locate templates dir relative to this file
TEMPLATES_DIR = Path(__file__).parent.parent / "app" / "templates"

# Import rules engine
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from app.form_rules import CROSS_FORM_RULES, T1_EXPORTS, T1_LINE_SOURCES


def _read(template_name: str) -> str:
    return (TEMPLATES_DIR / template_name).read_text(encoding="utf-8")


# ── 1. Rules engine self-consistency ─────────────────────────────────────────

class TestRulesEngineSanity:
    def test_all_templates_exist(self):
        for slug, rule in CROSS_FORM_RULES.items():
            p = TEMPLATES_DIR / rule["template"]
            assert p.exists(), f"{slug}: template {rule['template']} not found"

    def test_all_autosave_keys_are_unique(self):
        keys = [r["autosave_key"] for r in CROSS_FORM_RULES.values()]
        assert len(keys) == len(set(keys)), "Duplicate autosave_key in CROSS_FORM_RULES"

    def test_all_url_params_are_unique(self):
        params = [e["url_param"]
                  for r in CROSS_FORM_RULES.values()
                  for e in r["writes_to_t1"]]
        assert len(params) == len(set(params)), "Duplicate url_param values"

    def test_all_localStorage_keys_are_unique_per_form(self):
        for slug, rule in CROSS_FORM_RULES.items():
            keys = [e["localStorage_key"] for e in rule["writes_to_t1"]]
            assert len(keys) == len(set(keys)), \
                f"{slug}: duplicate localStorage_key in writes_to_t1"

    def test_sub_form_lines_match_t1_line_sources(self):
        """Every T1_LINE_SOURCES entry with source='sub_form' must appear in CROSS_FORM_RULES."""
        for line, info in T1_LINE_SOURCES.items():
            if info["source"] == "sub_form":
                slug = info["sub_form"]
                assert slug in CROSS_FORM_RULES, \
                    f"T1 line {line} references sub_form='{slug}' which is missing from CROSS_FORM_RULES"
                exports = [e["t1_line"] for e in CROSS_FORM_RULES[slug]["writes_to_t1"]]
                assert line in exports, \
                    f"T1 line {line} tagged sub_form='{slug}' but that form doesn't export line {line}"

    def test_t1_exports_have_unique_keys(self):
        keys = [e["localStorage_key"] for e in T1_EXPORTS]
        assert len(keys) == len(set(keys)), "Duplicate localStorage_key in T1_EXPORTS"


# ── 2. Sub-form writes the localStorage key ──────────────────────────────────

def _subform_ls_write_cases():
    for slug, rule in CROSS_FORM_RULES.items():
        for export in rule["writes_to_t1"]:
            yield pytest.param(
                rule["template"], export["localStorage_key"],
                id=f"{slug}::writes_localStorage::{export['localStorage_key']}",
            )

@pytest.mark.parametrize("template,key", _subform_ls_write_cases())
def test_subform_writes_localStorage_key(template, key):
    """Sub-form template must contain localStorage.setItem('KEY', ...)."""
    src = _read(template)
    assert f"localStorage.setItem('{key}'" in src or \
           f'localStorage.setItem("{key}"' in src, \
        f"{template}: missing localStorage.setItem('{key}', ...)"


# ── 3. Sub-form sends the URL param to T1 ────────────────────────────────────

def _subform_url_param_cases():
    for slug, rule in CROSS_FORM_RULES.items():
        for export in rule["writes_to_t1"]:
            yield pytest.param(
                rule["template"], export["url_param"],
                id=f"{slug}::sends_url_param::{export['url_param']}",
            )

@pytest.mark.parametrize("template,param", _subform_url_param_cases())
def test_subform_sends_url_param_to_t1(template, param):
    """Sub-form template must set the URL param when navigating back to T1."""
    src = _read(template)
    # Matches: p.set('param', ...) OR ?param= OR &param= in a URL string
    pattern = re.compile(
        r"\.set\s*\(\s*['\"]" + re.escape(param) + r"['\"]"   # URLSearchParams.set()
        r"|[?&]" + re.escape(param) + r"="                     # ?param= or &param=
        r"|['\"]" + re.escape(param) + r"="                    # 'param=' string literal
    )
    assert pattern.search(src), \
        f"{template}: does not send URL param '{param}' when returning to T1"


# ── 4. T1 handles every inbound URL param ────────────────────────────────────

def _t1_handles_url_param_cases():
    for slug, rule in CROSS_FORM_RULES.items():
        for export in rule["writes_to_t1"]:
            yield pytest.param(
                export["url_param"],
                id=f"t1_handles_url_param::{export['url_param']}_from_{slug}",
            )

@pytest.mark.parametrize("param", _t1_handles_url_param_cases())
def test_t1_handles_inbound_url_param(param):
    """t1.html must check urlP.has('param') and apply it."""
    src = _read("t1.html")
    # Should contain urlP.has('param') or urlP.get('param')
    pattern = re.compile(
        r"urlP\.has\s*\(\s*['\"]" + re.escape(param) + r"['\"]"
        r"|urlP\.get\s*\(\s*['\"]" + re.escape(param) + r"['\"]"
    )
    assert pattern.search(src), \
        f"t1.html: does not handle inbound URL param '{param}'"


# ── 5. T1 reads sub-form localStorage key on load ────────────────────────────

def _t1_reads_ls_key_cases():
    for slug, rule in CROSS_FORM_RULES.items():
        for export in rule["writes_to_t1"]:
            yield pytest.param(
                export["localStorage_key"],
                id=f"t1_reads_localStorage::{export['localStorage_key']}_from_{slug}",
            )

@pytest.mark.parametrize("key", _t1_reads_ls_key_cases())
def test_t1_reads_subform_localStorage_key(key):
    """t1.html must call localStorage.getItem('KEY') to pre-fill on load."""
    src = _read("t1.html")
    assert f"localStorage.getItem('{key}')" in src or \
           f'localStorage.getItem("{key}")' in src, \
        f"t1.html: does not read localStorage key '{key}' from sub-form"


# ── 6. T1 writes each export key to localStorage ─────────────────────────────

@pytest.mark.parametrize("export", T1_EXPORTS, ids=[e["localStorage_key"] for e in T1_EXPORTS])
def test_t1_writes_export_to_localStorage(export):
    """t1.html must write every T1_EXPORTS key so sub-forms can read it."""
    src = _read("t1.html")
    key = export["localStorage_key"]
    assert f"localStorage.setItem('{key}'" in src or \
           f'localStorage.setItem("{key}"' in src, \
        f"t1.html: does not write '{key}' to localStorage for sub-forms to read"


# ── 7. Sub-forms read T1 export keys ─────────────────────────────────────────

def _subform_reads_t1_cases():
    for slug, rule in CROSS_FORM_RULES.items():
        for t1_imp in rule["reads_from_t1"]:
            yield pytest.param(
                rule["template"], t1_imp["localStorage_key"],
                id=f"{slug}::reads_t1_key::{t1_imp['localStorage_key']}",
            )

@pytest.mark.parametrize("template,key", _subform_reads_t1_cases())
def test_subform_reads_t1_localStorage_key(template, key):
    """Sub-form template must read the T1 localStorage key it depends on."""
    src = _read(template)
    assert f"localStorage.getItem('{key}')" in src or \
           f'localStorage.getItem("{key}")' in src, \
        f"{template}: does not read T1 key '{key}' from localStorage"


# ── 8. T1 field IDs exist in t1.html ─────────────────────────────────────────

def _t1_field_id_cases():
    for slug, rule in CROSS_FORM_RULES.items():
        for export in rule["writes_to_t1"]:
            fid = export.get("t1_field_id")
            if fid:
                yield pytest.param(
                    fid,
                    id=f"t1_field_exists::id={fid}_from_{slug}",
                )

@pytest.mark.parametrize("field_id", _t1_field_id_cases())
def test_t1_field_id_exists_in_template(field_id):
    """Every t1_field_id named in the rules must exist as an HTML id in t1.html."""
    src = _read("t1.html")
    assert f'id="{field_id}"' in src or f"id='{field_id}'" in src, \
        f"t1.html: field id '{field_id}' not found — check rules engine"


# ── 9. T1 line source coverage ───────────────────────────────────────────────

class TestT1LineClassification:
    def test_all_sub_form_lines_are_in_rules(self):
        sub_lines = {ln for ln, info in T1_LINE_SOURCES.items()
                     if info["source"] == "sub_form"}
        rule_lines = {e["t1_line"]
                      for r in CROSS_FORM_RULES.values()
                      for e in r["writes_to_t1"]
                      if e["t1_line"] is not None}
        missing = sub_lines - rule_lines
        assert not missing, \
            f"T1_LINE_SOURCES has sub_form lines not in CROSS_FORM_RULES: {missing}"

    def test_no_undeclared_subform_lines(self):
        """No sub-form should target a T1 line unless it's classified as sub_form."""
        calc_and_input = {ln for ln, info in T1_LINE_SOURCES.items()
                          if info["source"] != "sub_form"}
        for slug, rule in CROSS_FORM_RULES.items():
            for export in rule["writes_to_t1"]:
                ln = export["t1_line"]
                if ln is None:
                    continue
                assert ln not in calc_and_input, (
                    f"{slug} exports to T1 line {ln} but that line is not "
                    f"classified as 'sub_form' in T1_LINE_SOURCES"
                )

    def test_calc_lines_not_claimed_by_sub_forms(self):
        calc_lines = {ln for ln, info in T1_LINE_SOURCES.items()
                      if info["source"] == "calc"}
        for slug, rule in CROSS_FORM_RULES.items():
            for export in rule["writes_to_t1"]:
                ln = export["t1_line"]
                assert ln not in calc_lines, (
                    f"{slug} tries to set T1 line {ln} which is auto-calculated — "
                    f"sub-forms must not overwrite calculated lines"
                )


# ── 10. autosave key round-trip ───────────────────────────────────────────────

def _autosave_cases():
    for slug, rule in CROSS_FORM_RULES.items():
        yield pytest.param(rule["template"], rule["autosave_key"], id=f"{slug}::autosave")

@pytest.mark.parametrize("template,key", _autosave_cases())
def test_form_saves_and_loads_own_autosave_key(template, key):
    """Every form must both write AND read its own autosave localStorage key."""
    src = _read(template)
    writes = (f"localStorage.setItem('{key}'" in src or
              f'localStorage.setItem("{key}"' in src or
              "localStorage.setItem(FORM_KEY" in src)
    reads  = (f"localStorage.getItem('{key}')" in src or
              f'localStorage.getItem("{key}")' in src or
              "localStorage.getItem(FORM_KEY" in src)
    assert writes, f"{template}: does not write autosave key '{key}'"
    assert reads,  f"{template}: does not read autosave key '{key}'"


# ── 11. "Save & Return to T1" button coverage ────────────────────────────────

def _save_return_cases():
    for slug, rule in CROSS_FORM_RULES.items():
        if rule["writes_to_t1"]:
            yield pytest.param(rule["template"], slug, id=f"{slug}::save_return_button")

@pytest.mark.parametrize("template,slug", _save_return_cases())
def test_form_has_save_and_return_button(template, slug):
    """Every form that exports to T1 must expose a Send/Return action."""
    src = _read(template)
    has_return = (
        "saveAndReturnToT1" in src
        or "sendToT1" in src
        or "/tax/t1" in src
    )
    assert has_return, \
        f"{template}: no 'Save & Return to T1' action found — " \
        f"user has no way to push data back to T1"


# ── 12. Back-link to T1 exists on every sub-form ─────────────────────────────

@pytest.mark.parametrize("slug,rule", CROSS_FORM_RULES.items(),
                         ids=list(CROSS_FORM_RULES.keys()))
def test_form_has_back_link_to_t1(slug, rule):
    """Every sub-form must have a navigational link back to T1."""
    src = _read(rule["template"])
    assert "/tax/t1" in src, \
        f"{rule['template']}: no link back to /tax/t1 found"
