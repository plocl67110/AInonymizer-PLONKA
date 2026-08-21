#!/usr/bin/env python3
"""
AInonymizer — pseudonymiseur local headless (Python)

Usage :
    Placer vos fichiers PDF/DOCX/MD dans le dossier input/,
    puis exécuter :
        pip install -r requirements.txt
        python ainonymizer.py

Sortie : dossier output/ créé à côté du script.
  • {nom}_anonymise.md   — texte pseudonymisé (optimisé LLM)
  • {nom}_mapping.json  — table pseudonyme → valeur originale
  • corpus_mapping.json — table globale du corpus
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from anonymizer import Entity, analyze, apply_pseudonyms
from extractor import extract
from gui import launch_gui
from pseudo_map import PseudoMap

SUPPORTED = {".pdf", ".docx", ".md", ".markdown"}
_IGNORED = {"readme.md", "readme.markdown", "claude.md"}


# ═══════════════════════════════════════════════════════════════════════
#  Découverte des fichiers
# ═══════════════════════════════════════════════════════════════════════

def find_documents(input_dir: Path) -> list[Path]:
    """Liste les fichiers supportés dans input/ (hors fichiers meta)."""
    if not input_dir.exists():
        return []
    return sorted(
        p for p in input_dir.iterdir()
        if p.is_file()
        and p.suffix.lower() in SUPPORTED
        and p.name.lower() not in _IGNORED
    )


# ═══════════════════════════════════════════════════════════════════════
#  Formatage Markdown optimisé LLM
# ═══════════════════════════════════════════════════════════════════════

_MULTI_BLANK = re.compile(r"\n{3,}")


def _to_markdown(filename: str, anonymized_text: str) -> str:
    """
    Produit un Markdown propre pour consommation LLM.
    - En-tête indiquant la source
    - Texte avec pseudonymes entre crochets : [PERSONNE_001]
    - Pas de métadonnées superflues
    """
    body = _MULTI_BLANK.sub("\n\n", anonymized_text).strip()
    return f"# {filename}\n\n{body}\n"


# ═══════════════════════════════════════════════════════════════════════
#  Traitement d'un fichier
# ═══════════════════════════════════════════════════════════════════════

def _stats(entities: list[Entity]) -> str:
    enabled = [e for e in entities if e.enabled]
    by_cat: dict[str, int] = {}
    for e in enabled:
        by_cat[e.category] = by_cat.get(e.category, 0) + 1
    summary = ", ".join(f"{k}:{v}" for k, v in sorted(by_cat.items()))
    return f"{len(enabled)} entités ({summary})"


def process(
    path: Path,
    pseudo_map: PseudoMap,
    output_dir: Path,
    mappings_dir: Path,
    disabled_categories: frozenset[str] = frozenset(),
) -> dict[str, str]:
    """
    Extrait, analyse et pseudonymise un fichier.
    Écrit les fichiers de sortie.
    Retourne la table de correspondance du fichier (peut être vide si échec).
    """
    print(f"  {path.name}")

    try:
        text = extract(path)
    except Exception as exc:
        print(f"    ✗ extraction : {exc}")
        return {}

    if not text.strip():
        print("    ✗ texte vide — PDF scanné ou protégé ?")
        return {}

    # disabled_categories reflète le choix explicite de l'utilisateur dans
    # la GUI (y compris si Avocats/Magistrats a été coché pour être activé) ;
    # analyze() est l'unique point qui détermine enabled, sans logique
    # cachée en amont susceptible de contredire ce choix.
    entities = analyze(text, pseudo_map, frozenset(disabled_categories))
    print(f"    {_stats(entities)}")

    anonymized = apply_pseudonyms(text, entities)

    stem = path.stem
    md_path = output_dir / f"{stem}_anonymise.md"
    mapping_path = mappings_dir / f"{stem}_mapping.json"

    md_path.write_text(_to_markdown(path.name, anonymized), encoding="utf-8")

    file_table: dict[str, str] = {
        e.pseudonym: e.text for e in entities if e.enabled
    }
    mapping_data = {
        "source": path.name,
        "date": str(date.today()),
        "entites": file_table,
    }
    mapping_path.write_text(
        json.dumps(mapping_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return file_table


# ═══════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════

def main() -> None:
    if getattr(sys, "frozen", False):
        root = Path(sys.executable).parent.resolve()
    else:
        root = Path(__file__).parent.resolve()

    input_dir = root / "input"
    input_dir.mkdir(exist_ok=True)
    output_dir = root / "output"
    output_dir.mkdir(exist_ok=True)
    mappings_dir = output_dir / "mappings"
    mappings_dir.mkdir(exist_ok=True)

    docs = find_documents(input_dir)

    disabled_categories = launch_gui(len(docs))

    if not docs:
        print("Aucun fichier PDF / DOCX / MD trouvé dans le dossier input/.")
        sys.exit(0)

    print(f"AInonymizer — {len(docs)} fichier(s) trouvé(s)\n")

    # PseudoMap partagée : garantit la cohérence cross-document
    pseudo_map = PseudoMap()
    corpus_table: dict[str, str] = {}

    for path in docs:
        file_table = process(path, pseudo_map, output_dir, mappings_dir, disabled_categories)
        corpus_table.update(file_table)

    corpus_path = mappings_dir / "corpus_mapping.json"
    corpus_path.write_text(
        json.dumps(
            {
                "date": str(date.today()),
                "entites": corpus_table,
                "credits": (
                    "Conçu gratuitement par Florence Chatelot, formatrice aux outils IA. "
                    "Si cet outil vous est utile, offrez lui quelque chose : https://florence-chatelot.fr/stripe"
                ),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    total = len(corpus_table)
    print(f"\n✓ Sortie : {output_dir}/")
    print(f"  {total} entité(s) pseudonymisée(s) au total")
    print(f"  Table globale : mappings/corpus_mapping.json")
    print()
    print("─" * 62)
    print("  Outil conçu par Florence Chatelot, formatrice en outils IA.")
    print("  Offrez-lui un café : https://florence-chatelot.fr/stripe")
    print("─" * 62)


if __name__ == "__main__":
    main()
