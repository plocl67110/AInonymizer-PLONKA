# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run tests (no external dependencies beyond the project's own)
python test_ainonymizer.py

# Run AInonymizer on all PDF/DOCX/MD files in input/
python ainonymizer.py

# Install dependencies
pip install -r requirements.txt

# Build Windows executable
python -m PyInstaller --onefile --name ainonymizer ainonymizer.py
```

## Architecture

**AInonymizer** is a local, rule-based pseudonymizer for French-language documents containing RGPD-sensitive data. It processes PDF, DOCX, and Markdown files through a 4-pass pipeline and outputs anonymized Markdown + JSON mapping files, ready for LLM consumption.

### Pipeline (anonymizer.py)

Four passes in sequence:

1. **Regex detection** (`regex_fr.py`) — finds PII using compiled patterns + checksums (Luhn for SIREN, mod-97 for IBAN, key validation for NIR)
2. **Post-processing** (`juritools.py`) — reclassifies dates (procedural vs. birth/death), propagates multi-occurrences, finds orthographic variants (Levenshtein ≤ 2), trims particles, cross-references physical/legal persons
3. **Deduplication** (`anonymizer.py:_dedupe`) — resolves overlaps by priority score + span length
4. **Pseudonym assignment** (`pseudo_map.py`) — maps normalized text → `CATEGORY_NNN`, consistent across the whole corpus

### Key design decisions

- **`PseudoMap`** is shared across all documents in a run, guaranteeing cross-document consistency (same entity → same pseudonym). It also tracks each entity's *canonical category* (the category of its first occurrence), which `analyze()` uses to decide `enabled` — so the same person is never pseudonymized in one occurrence and left in clear text in another, even if detected under different category patterns (e.g. `AVOCAT` via "Maître X" then `PERSONNE` via "M. X").
- Avocats and magistrats are **disabled by default** (`enabled=False`, category-based, controlled solely by `disabled_categories` in `analyze()`) per CNIL deliberation 01-057 on the diffusion of court decisions — note this deliberation targets public online diffusion of jurisprudence databases specifically; applying it to internal, LLM-bound document processing is an extrapolation worth documenting explicitly for users. Disabled entities are **not** replaced in the output text and **not** included in the mapping JSON (only `enabled=True` entities populate the mapping — see `ainonymizer.py::process`). The GUI checkbox for these two categories is fully respected: checking "Avocats"/"Magistrats" re-enables their pseudonymization, since `mark_professionals_disabled`'s hardcoded override was removed — `disabled_categories` (from `gui.py`, default `{AVOCAT, MAGISTRAT}`) is now the single source of truth, passed directly into `analyze()`.
- `regex_fr.py`'s NIR pattern accepts Corsican department codes (`2A`/`2B`), matching the checksum logic in `_validate_nir` which already handled their conversion.
- Regex-based person-name detection (`find_person_names`) has structural recall limits: names in free narrative text without a preceding civility/role marker, or in lowercase, are not caught. This tool is a strong first-pass filter, not a guarantee of exhaustive anonymization — human review of the output before sending to an external LLM remains advisable, especially for narrative sections.
- `ainonymizer.py` scans the `input/` subdirectory for files to process (non-recursive). When bundled with PyInstaller (`sys.frozen`), it uses `sys.executable` to locate the root directory instead of `__file__`. Both `input/` and `output/` are gitignored (content only) — they may contain real PII.
- The `output/` directory is gitignored — it may contain real PII from production use.
- The `input/` directory is gitignored (contents only, `.gitkeep` tracked) — drop documents to process there.

### Module responsibilities

| File | Role |
|---|---|
| `ainonymizer.py` | Entry point: file discovery, orchestration, Markdown + JSON output |
| `anonymizer.py` | Pipeline orchestration, `Entity` dataclass, deduplication |
| `regex_fr.py` | All regex patterns and checksum validators; defines `RawMatch` |
| `juritools.py` | Deterministic post-processing passes |
| `pseudo_map.py` | Cross-document pseudonym table |
| `extractor.py` | Text extraction from PDF (MuPDF/fitz), DOCX (python-docx), MD |

### Adding a new PII category

1. Add detection logic in `regex_fr.py` (new pattern in `_STRUCTURED` or a new `find_*` function)
2. Export the new function and call it in `anonymizer.py:analyze()`
3. Add the priority score to `_PRIORITY` in `anonymizer.py`
4. Add a test case in `test_ainonymizer.py`
