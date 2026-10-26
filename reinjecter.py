import json
import re
import sys
from pathlib import Path

PSEUDO = re.compile(r"\[([A-Z_]+_\d{3})\]")
TABLE_PAR_DEFAUT = Path("output/mappings/corpus_mapping.json")


def charger_table(chemin: Path) -> dict[str, str]:
    data = json.loads(chemin.read_text(encoding="utf-8"))
    return data["entites"]


def restaurer(texte: str, table: dict[str, str]) -> tuple[str, list[str]]:
    manquants: set[str] = set()

    def remplace(m: re.Match) -> str:
        cle = m.group(1)
        if cle in table:
            return table[cle].replace("\n", " ")
        manquants.add(cle)
        return m.group(0)

    return PSEUDO.sub(remplace, texte), sorted(manquants)


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print("Usage : python reinjecter.py reponse.md [corpus_mapping.json]")
        return 1

    source = Path(sys.argv[1])
    table_path = Path(sys.argv[2]) if len(sys.argv) == 3 else TABLE_PAR_DEFAUT

    table = charger_table(table_path)
    texte, manquants = restaurer(source.read_text(encoding="utf-8"), table)

    cible = source.with_name(source.stem + "_restaure.md")
    cible.write_text(texte, encoding="utf-8")
    print(f"Fichier restauré (données personnelles, à garder en local) : {cible}")

    if manquants:
        print("Pseudonymes absents de la table, laissés tels quels :", ", ".join(manquants))
    return 0


if __name__ == "__main__":
    sys.exit(main())