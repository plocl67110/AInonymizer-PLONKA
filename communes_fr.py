"""
Détection complémentaire des communes françaises à partir du COG INSEE.

Fonctionne :
- depuis le projet Python ;
- dans un EXE PyInstaller onefile ;
- avec data/communes2026.csv embarqué dans l'EXE.

Les communes sont retournées comme des entités LIEU.
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

from regex_fr import RawMatch


# ---------------------------------------------------------------------------
# Localisation du fichier des communes
# ---------------------------------------------------------------------------

if getattr(sys, "frozen", False):
    # PyInstaller onefile extrait les fichiers embarqués dans _MEIPASS.
    _BASE_DIR = Path(sys._MEIPASS)
else:
    # Exécution normale depuis le projet Python.
    _BASE_DIR = Path(__file__).resolve().parent

_DATA_FILE = _BASE_DIR / "data" / "communes2026.csv"


# Cache chargé une seule fois.
_COMMUNES: dict[str, str] | None = None

# Communes réelles dont le nom est aussi un mot très courant du français
# juridique/administratif, susceptible d'apparaître capitalisé en début de
# phrase ou de titre de section (donc non filtré par la seule contrainte de
# casse). Repéré sur des documents juridiques réels. Normalisé (casefold).
_AMBIGUOUS_COMMUNES = {
    "force", "chambre", "contre", "faux", "fors", "titre", "frais",
    "cesse", "mars", "celle", "grave", "omet", "bonne", "passage",
}

# Mots de liaison légitimement en minuscule à l'intérieur d'un nom de
# commune composé (Châlons-en-Champagne, Aix-en-Provence, Neuilly-sur-Seine,
# La Chapelle-sous-Uchon...). Jamais en première position du nom.
_LOWERCASE_LINK_WORDS = {
    "en", "sur", "sous", "de", "du", "des", "la", "le", "les", "l",
    "aux", "au", "et", "ou", "d",
}


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def _normalize(value: str) -> str:
    """
    Normalise un nom de commune pour les comparaisons.

    La comparaison est :
    - insensible à la casse ;
    - tolérante aux espaces multiples.
    """
    value = value.strip().casefold()
    value = re.sub(r"\s+", " ", value)
    return value


# ---------------------------------------------------------------------------
# Chargement du COG INSEE
# ---------------------------------------------------------------------------

def _load_communes() -> dict[str, str]:
    """
    Charge la liste des communes depuis communes2026.csv.

    Le fichier fourni par l'INSEE utilise des virgules comme séparateurs.
    L'encodage attendu est UTF-8 avec éventuel BOM.

    Retourne :
        {nom_normalisé: nom_canonique}
    """

    global _COMMUNES

    if _COMMUNES is not None:
        return _COMMUNES

    communes: dict[str, str] = {}

    if not _DATA_FILE.exists():
        _COMMUNES = communes
        return communes

    with _DATA_FILE.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as f:

        reader = csv.DictReader(f)

        for row in reader:

            # On ne conserve que les communes.
            if (row.get("TYPECOM") or "").strip() != "COM":
                continue

            # NCCENR : nom enrichi
            # LIBELLE : libellé officiel
            for field in ("NCCENR", "LIBELLE"):

                value = (row.get(field) or "").strip()

                if len(value) < 3:
                    continue

                # Version sans article initial.
                #
                # Exemples :
                # L'Abergement-Clémenciat -> Abergement-Clémenciat
                # La Rochelle             -> Rochelle
                #
                # On conserve cependant aussi la forme originale.
                clean = re.sub(
                    r"^(?:L'|La |Le |Les |Las |Los )",
                    "",
                    value,
                    flags=re.IGNORECASE,
                ).strip()

                if len(clean) >= 3:
                    communes[_normalize(clean)] = clean

                communes[_normalize(value)] = value

    _COMMUNES = communes
    return communes


# ---------------------------------------------------------------------------
# Détection
# ---------------------------------------------------------------------------

def communes_count() -> int:
    """Nombre de communes distinctes chargées depuis le COG INSEE (valeurs
    canoniques uniques — le dict interne contient aussi des clés
    normalisées en double, sans article, etc.)."""
    return len(set(_load_communes().values()))


def find_communes(text: str) -> list[RawMatch]:
    """
    Détecte les communes françaises présentes dans un texte.

    La recherche :
    - est insensible à la casse ;
    - respecte les frontières de mots ;
    - accepte les accents ;
    - accepte les noms composés ;
    - privilégie les noms les plus longs ;
    - évite les chevauchements.

    Exemple :

        Strasbourg
        Haguenau
        Saint-Louis
        Châlons-en-Champagne
        Aix-en-Provence
    """

    if not text:
        return []

    communes = _load_communes()

    if not communes:
        return []

    # Les noms les plus longs sont testés en premier.
    # Cela évite qu'un nom court soit retenu avant un nom composé.
    names = sorted(
        communes.keys(),
        key=len,
        reverse=True,
    )

    matches: list[RawMatch] = []

    # Intervalles déjà occupés.
    occupied: list[tuple[int, int]] = []

    for normalized_name in names:

        canonical = communes[normalized_name]

        # Le nom provient du CSV : re.escape() protège tous les caractères
        # spéciaux éventuels.
        pattern = re.compile(
            rf"(?<![\wÀ-ÿ])"
            rf"{re.escape(canonical)}"
            rf"(?![\wÀ-ÿ])",
            re.IGNORECASE,
        )

        for match in pattern.finditer(text):

            start = match.start()
            end = match.end()

            # Évite les chevauchements avec une commune déjà retenue.
            if any(
                start < old_end and old_start < end
                for old_start, old_end in occupied
            ):
                continue

            value = match.group(0).strip()

            # Évite les noms trop courts.
            if len(value) < 4:
                continue

            # Un nom de commune est toujours capitalisé dans un texte
            # français (chaque segment : "Saint-Louis", "Aix-en-Provence").
            # De nombreuses communes rurales partagent leur nom avec des
            # mots du langage courant (Force, Chambre, Faux, Fors, Titre,
            # Cesse, Mars...) qui, eux, apparaissent en minuscule en
            # milieu de phrase — le match insensible à la casse ci-dessus
            # sert uniquement à trouver le candidat, la casse réelle du
            # texte tranche pour le retenir ou non.
            # Un nom de commune est toujours capitalisé dans un texte
            # français, à l'exception des mots de liaison internes
            # (Châlons-en-Champagne, Aix-en-Provence, Neuilly-sur-Seine...).
            # Le premier segment reste l'ancre obligatoire : jamais de
            # commune légitimement détectée en commençant par un mot de
            # liaison minuscule.
            segments = [seg for seg in re.split(r"[\s'’-]+", value) if seg]
            if not segments or not segments[0][:1].isupper():
                continue
            if not all(
                seg[:1].isupper() or seg.casefold() in _LOWERCASE_LINK_WORDS
                for seg in segments[1:]
            ):
                continue

            if _normalize(value) in _AMBIGUOUS_COMMUNES:
                continue

            occupied.append((start, end))

            matches.append(
                RawMatch(
                    start=start,
                    end=end,
                    text=value,
                    category="LIEU",
                    confidence=0.88,
                    source="commune_insee",
                )
            )

    return sorted(
        matches,
        key=lambda m: (m.start, m.end),
    )


# ---------------------------------------------------------------------------
# Test rapide
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    communes = _load_communes()

    print(f"Fichier COG : {_DATA_FILE}")
    print(f"Communes chargées : {len(communes)}")

    texte = (
        "Jean Dupont est né à Strasbourg. "
        "Il réside à Haguenau. "
        "Le tribunal de Colmar traite le dossier. "
        "La procédure concerne Châlons-en-Champagne."
    )

    print()
    print("Détections :")

    for match in find_communes(texte):
        print(
            f"  {match.text!r} -> "
            f"{match.category} "
            f"({match.source})"
        )