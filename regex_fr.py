from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Callable, Optional
from datetime import datetime


# ============================================================================
# Modèle commun
# ============================================================================

@dataclass
class RawMatch:
    start: int
    end: int
    text: str
    category: str
    confidence: float = 1.0
    source: str = "regex"


# ============================================================================
# Utilitaires
# ============================================================================

def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def _strip_accents(s: str) -> str:
    return "".join(
        c
        for c in unicodedata.normalize("NFD", s.casefold())
        if unicodedata.category(c) != "Mn"
    )


def _norm_upper(s: str) -> str:
    return unicodedata.normalize("NFC", s).upper().strip()


def _luhn(s: str) -> bool:
    if not s.isdigit():
        return False

    total = 0
    parity = len(s) % 2

    for i, char in enumerate(s):
        digit = int(char)

        if i % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9

        total += digit

    return total % 10 == 0


# ============================================================================
# Validateurs
# ============================================================================

def _validate_siren(s: str) -> bool:
    clean = _digits(s)

    return (
        len(clean) == 9
        and not clean.startswith("0")
        and len(set(clean)) > 1
        and _luhn(clean)
    )


def _validate_siret(s: str) -> bool:
    clean = _digits(s)

    return (
        len(clean) == 14
        and not clean.startswith("0")
        and _validate_siren(clean[:9])
        and _luhn(clean)
    )


def _validate_nir(s: str) -> bool:
    """
    Valide un NIR français, y compris les départements corses 2A / 2B.
    """

    raw = re.sub(r"[\s./-]", "", s).upper()

    m = re.fullmatch(
        r"([12])"
        r"(\d{2})"
        r"(\d{2})"
        r"(\d{2}|2A|2B)"
        r"(\d{3})"
        r"(\d{3})"
        r"(\d{2})",
        raw,
    )

    if not m:
        return False

    sex, year, month, dept, commune, order, key = m.groups()

    if not 1 <= int(month) <= 12:
        return False

    # Calcul officiel du NIR pour la Corse :
    # 2A -> 19
    # 2B -> 18
    dept_num = {
        "2A": "19",
        "2B": "18",
    }.get(dept, dept)

    base = int(
        sex
        + year
        + month
        + dept_num
        + commune
        + order
    )

    expected_key = 97 - (base % 97)

    return expected_key == int(key)


_IBAN_LENGTHS = {
    "FR": 27,
    "DE": 22,
    "BE": 16,
    "CH": 21,
    "LU": 20,
    "NL": 18,
    "GB": 22,
    "ES": 24,
    "IT": 27,
    "AT": 20,
    "MC": 27,
}


def _validate_iban(s: str) -> bool:
    clean = re.sub(r"\s+", "", s).upper()

    if not re.fullmatch(
        r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}",
        clean,
    ):
        return False

    expected_len = _IBAN_LENGTHS.get(clean[:2])

    if expected_len is not None and len(clean) != expected_len:
        return False

    numeric = "".join(
        str(ord(c) - 55) if c.isalpha() else c
        for c in clean[4:] + clean[:4]
    )

    remainder = 0

    for char in numeric:
        remainder = (remainder * 10 + int(char)) % 97

    return remainder == 1


# ============================================================================
# Déduplication
# ============================================================================

# Priorité métier utilisée pour trancher les chevauchements entre catégories
# différentes (ex: DATE vs DATE_NAISSANCE, EMAIL vs LIEU/PERSONNE partiels).
# Alignée sur la table _PRIORITY d'anonymizer.py — à garder synchronisée si
# l'une des deux évolue.
# Table de priorités unique, partagée avec anonymizer.py.
# Un LIEU ou une COMMUNE ne doit jamais écraser une personne détectée.
CATEGORY_PRIORITY = {
    "EMAIL": 10,
    "DATE_NAISSANCE": 10,
    "AVOCAT": 9,
    "MAGISTRAT": 9,
    "JURIDICTION": 8,
    "PERSONNE_MORALE": 7,
    "NUM_DOSSIER": 7,
    "NIR": 6,
    "IBAN": 6,
    "SIREN": 6,
    "SIRET": 6,
    "PLAQUE": 6,
    "TEL": 5,
    "ADRESSE": 4,
    "PERSONNE": 3,
    "LIEU": 2,
    "COMMUNE": 2,
    "DATE": 1,
}

# Alias interne utilisé par _dedupe_overlaps.
_CATEGORY_PRIORITY = CATEGORY_PRIORITY


def _dedupe_overlaps(matches: list[RawMatch]) -> list[RawMatch]:
    """
    Supprime les chevauchements.

    Priorité :
        1. priorité métier de la catégorie (_CATEGORY_PRIORITY) ;
        2. confiance ;
        3. longueur ;
        4. position.
    """

    kept: list[RawMatch] = []

    candidates = sorted(
        matches,
        key=lambda m: (
            -_CATEGORY_PRIORITY.get(m.category, 0),
            -m.confidence,
            -(m.end - m.start),
            m.start,
        ),
    )

    for match in candidates:
        overlaps = any(
            match.start < existing.end
            and existing.start < match.end
            for existing in kept
        )

        if overlaps:
            continue

        kept.append(match)

    return sorted(
        kept,
        key=lambda m: (m.start, m.end),
    )


# ============================================================================
# Dates
# ============================================================================

_MONTH = (
    r"janvier|février|mars|avril|mai|juin|juillet|"
    r"août|septembre|octobre|novembre|décembre"
)


def _validate_date(s: str) -> bool:
    """
    Valide réellement une date.

    Exemples :
        12/05/1990       -> True
        03-06-2023       -> True
        31/02/2020       -> False
        29/02/2024       -> True
        29/02/2023       -> False
        12 février 2026  -> True
    """

    value = s.strip()

    # Date numérique
    m = re.fullmatch(
        r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})",
        value,
    )

    if m:
        day, month, year = map(int, m.groups())

        if year < 100:
            year += 2000

        try:
            datetime(year, month, day)
            return True
        except ValueError:
            return False

    # Date française en toutes lettres
    m = re.fullmatch(
        rf"(\d{{1,2}})\s+({_MONTH})\s+(\d{{4}})",
        value,
        re.IGNORECASE,
    )

    if not m:
        return False

    day = int(m.group(1))
    month_name = _strip_accents(m.group(2))
    year = int(m.group(3))

    months = {
        "janvier": 1,
        "fevrier": 2,
        "mars": 3,
        "avril": 4,
        "mai": 5,
        "juin": 6,
        "juillet": 7,
        "aout": 8,
        "septembre": 9,
        "octobre": 10,
        "novembre": 11,
        "decembre": 12,
    }

    month = months.get(month_name)

    if month is None:
        return False

    try:
        datetime(year, month, day)
        return True
    except ValueError:
        return False


# ============================================================================
# Données structurées
# ============================================================================

_STRUCTURED: list[
    tuple[
        str,
        re.Pattern,
        Optional[int],
        Optional[Callable[[str], bool]],
        float,
    ]
] = [

    # ------------------------------------------------------------------
    # EMAIL
    # ------------------------------------------------------------------

    (
        "EMAIL",
        re.compile(
            r"(?<![\w.+-])"
            r"[A-Za-z0-9._%+-]+"
            r"@"
            r"(?:"
            r"[A-Za-z0-9]"
            r"(?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
            r"\."
            r")+"
            r"[A-Za-z]{2,63}"
            r"(?![\w-])"
        ),
        None,
        None,
        1.0,
    ),

    # ------------------------------------------------------------------
    # TELEPHONE FRANÇAIS
    # ------------------------------------------------------------------

    (
        "TEL",
        re.compile(
            r"(?<!\d)"
            r"(?:(?:\+33|0033)[ .-]?[1-9]|0[1-9])"
            r"(?:[ .-]?\d{2}){4}"
            r"(?!\d)"
        ),
        None,
        None,
        1.0,
    ),

    # ------------------------------------------------------------------
    # NIR / SÉCURITÉ SOCIALE
    # ------------------------------------------------------------------

    (
        "NIR",
        re.compile(
            r"(?<!\d)"
            r"[12][ .]?\d{2}[ .]?\d{2}[ .]?"
            r"(?:\d{2}|2[AaBb])"
            r"[ .]?\d{3}[ .]?\d{3}[ .]?\d{2}"
            r"(?!\d)"
        ),
        None,
        _validate_nir,
        1.0,
    ),

    # ------------------------------------------------------------------
    # IBAN
    # ------------------------------------------------------------------

    (
        "IBAN",
        re.compile(
            r"(?<![A-Z0-9])"
            r"[A-Z]{2}\d{2}"
            r"(?:[ ]?[A-Z0-9]){11,30}"
            r"(?![A-Z0-9])",
            re.IGNORECASE,
        ),
        None,
        _validate_iban,
        1.0,
    ),

    # ------------------------------------------------------------------
    # SIRET
    # ------------------------------------------------------------------

    (
        "SIRET",
        re.compile(
            r"(?<![\d/.-])"
            r"\d{3}[ .]?\d{3}[ .]?\d{3}[ .]?\d{5}"
            r"(?!\d)"
        ),
        None,
        _validate_siret,
        0.98,
    ),

    # ------------------------------------------------------------------
    # SIREN
    # ------------------------------------------------------------------

    (
        "SIREN",
        re.compile(
            r"(?<![\d/.-])"
            r"\d{3}[ .]?\d{3}[ .]?\d{3}"
            r"(?!\d)"
        ),
        None,
        _validate_siren,
        0.98,
    ),

    # ------------------------------------------------------------------
    # PLAQUE SIV
    # ------------------------------------------------------------------

    (
        "PLAQUE",
        re.compile(
            r"(?<![A-Z0-9])"
            r"[A-HJ-NP-TV-Z]{2}"
            r"[ -]?\d{3}"
            r"[ -]?[A-HJ-NP-TV-Z]{2}"
            r"(?![A-Z0-9])",
            re.IGNORECASE,
        ),
        None,
        None,
        0.98,
    ),

    # ------------------------------------------------------------------
    # ANCIENNE PLAQUE
    # ------------------------------------------------------------------

    (
        "PLAQUE",
        re.compile(
            r"(?<![A-Z0-9])"
            r"\d{1,4}"
            r"[ -]?[A-Z]{2,3}"
            r"[ -]?\d{2}"
            r"(?![A-Z0-9])",
            re.IGNORECASE,
        ),
        None,
        None,
        0.92,
    ),

    # ------------------------------------------------------------------
    # NUMÉRO DE DOSSIER
    # ------------------------------------------------------------------

    (
        "NUM_DOSSIER",
        re.compile(
            r"(?i)\b"
            r"(?:dossier|affaire)"
            r"\s*"
            r"(?:n[°o]\s*)?"
            r"[:#-]?\s*"
            r"[0-9][A-Z0-9./_-]{2,30}"
            r"\b"
        ),
        None,
        None,
        0.95,
    ),

    # ------------------------------------------------------------------
    # RÉFÉRENCE RG
    # ------------------------------------------------------------------

    (
        "NUM_DOSSIER",
        re.compile(
            r"(?i)\bRG"
            r"\s*(?:n[°o]\s*)?"
            r"\d{1,6}"
            r"(?:[/-][A-Z0-9]+){1,3}"
            r"\b"
        ),
        None,
        None,
        0.95,
    ),

    # ------------------------------------------------------------------
    # DATE FRANÇAISE
    # ------------------------------------------------------------------

    (
        "DATE",
        re.compile(
            rf"\b"
            rf"\d{{1,2}}\s+(?:{_MONTH})\s+\d{{4}}"
            rf"\b",
            re.IGNORECASE,
        ),
        None,
        _validate_date,
        0.98,
    ),

    # ------------------------------------------------------------------
    # DATE NUMÉRIQUE
    # ------------------------------------------------------------------

    (
        "DATE",
        re.compile(
            r"\b"
            r"(?:"
            r"(?:0?[1-9]|[12]\d|3[01])"
            r"[/-]"
            r"(?:0?[1-9]|1[0-2])"
            r"[/-]"
            r"(?:\d{2}|\d{4})"
            r")"
            r"\b"
        ),
        None,
        _validate_date,
        0.95,
    ),
]


def find_structured_pii(text: str) -> list[RawMatch]:
    """
    Détecte les données personnelles structurées :

    - EMAIL
    - TEL
    - NIR
    - IBAN
    - SIREN
    - SIRET
    - PLAQUE
    - NUM_DOSSIER
    - DATE

    Les validateurs sont appliqués lorsqu'ils existent.

    Le SIRET bénéficie en plus d'une détection contextuelle lorsqu'il
    est explicitement précédé du libellé "SIRET".
    """

    out: list[RawMatch] = []

    for category, pattern, _, validator, confidence in _STRUCTURED:

        for match in pattern.finditer(text):

            value = match.group(0)

            if validator is not None:
                try:
                    if not validator(value):
                        continue
                except (ValueError, TypeError):
                    continue

            out.append(
                RawMatch(
                    start=match.start(),
                    end=match.end(),
                    text=value,
                    category=category,
                    confidence=confidence,
                    source="structured",
                )
            )

    # ------------------------------------------------------------------
    # SIRET avec contexte explicite
    #
    # Exemple accepté :
    #     SIRET n° 810 574 568 00034
    #
    # Le libellé "SIRET" est obligatoire.
    # Un simple "n° 810 574 568 00034" n'est pas ajouté par cette règle.
    # ------------------------------------------------------------------

    siret_context_pattern = re.compile(
        r"(?i)\bSIRET\b"
        r"[ \t]*(?:n[°o]\s*)?"
        r"(?P<siret>"
        r"\d{3}[ .]?\d{3}[ .]?\d{3}[ .]?\d{5}"
        r")"
    )

    for match in siret_context_pattern.finditer(text):

        value = match.group("siret")

        out.append(
            RawMatch(
                start=match.start("siret"),
                end=match.end("siret"),
                text=value,
                category="SIRET",
                confidence=1.0 if _validate_siret(value) else 0.75,
                source="siret_context" if _validate_siret(value) else "siret_context_unchecked",
            )
        )

    # ------------------------------------------------------------------
    # DATE DE NAISSANCE
    # ------------------------------------------------------------------

    for i, match in enumerate(out):
        if match.category != "DATE":
            continue

        context_before = text[max(0, match.start - 30):match.start]

        if re.search(
            r"\bné(?:e)?\s+le\s*$",
            context_before,
            re.IGNORECASE,
        ):
            out[i] = RawMatch(
                start=match.start,
                end=match.end,
                text=match.text,
                category="DATE_NAISSANCE",
                confidence=match.confidence,
                source="structured",
            )

    return _dedupe_overlaps(out)


# ============================================================================
# Juridictions
# ============================================================================

_JURIDICTIONS = [

    re.compile(
        r"\b"
        r"(?:Tribunal|Cour|Conseil|Juridiction)"
        r"\s+"
        r"(?:"
        r"judiciaire|"
        r"administratif|"
        r"de\s+commerce|"
        r"de\s+proximité|"
        r"des\s+prud['’]hommes|"
        r"d['’]appel|"
        r"de\s+cassation"
        r")"
        r"\b",
        re.IGNORECASE,
    ),

    re.compile(
        r"\b"
        r"(?:Tribunal|Cour)"
        r"\s+"
        r"(?:"
        r"judiciaire|"
        r"administratif|"
        r"commercial|"
        r"correctionnel|"
        r"criminel"
        r")"
        r"\b",
        re.IGNORECASE,
    ),
]


def find_juridictions(text: str) -> list[RawMatch]:
    out: list[RawMatch] = []

    for pattern in _JURIDICTIONS:

        for match in pattern.finditer(text):

            out.append(
                RawMatch(
                    match.start(),
                    match.end(),
                    match.group(0),
                    "JURIDICTION",
                    0.98,
                    "juridiction",
                )
            )

    return _dedupe_overlaps(out)


# ============================================================================
# Personnes morales / sociétés
# ============================================================================

_FORMES = (
    r"SASU?|SARL|EURL|SA|SCI|SCP|SCM|SNC|GIE|"
    r"SELARL|SELAS|SEL|SELAFA|SELCA|GAEC|EARL|"
    r"SCA|SCIC|SCOP"
)


_SOC_NAME = (
    r"(?:"
    r"[A-ZÀ-ÖØ-Þ0-9]"
    r"[A-Za-zÀ-ÿ0-9&'’./-]{2,50}"
    r"(?:"
    r"[ \t'-]+"
    r"[A-ZÀ-ÖØ-Þ0-9]"
    r"[A-Za-zÀ-ÿ0-9&'’./-]{2,50}"
    r"){0,7}"
    r")"
)


_COMPANY_STOPWORDS = {
    "CABINET",
    "AVOCAT",
    "AVOCATS",
    "FONDATEUR",
    "FONDATRICE",
    "TRIBUNAL",
    "PROXIMITE",
    "DOSSIER",
    "TEL",
    "TELEPHONE",
    "INSCRIT",
    "INSCRITE",
    "SOCIETE",
    "REPRESENTE",
    "REPRESENTEE",
    "ASSOCIE",
    "ASSOCIEE",
    "GERANT",
    "GERANTE",
    "SOCIAL",
    "DEA",
    "ET",
    "ENTRE",
    "CONTRE",
    "SUR",
    "PAR",
    "POUR",
    "DANS",
    "AVEC",
    "ATTENDU",
    "QUE",
    "VU",
    "CONSIDERANT",
    "ORDONNE",
    "CONDAMNE",
    "DEBOUTE",
    "DIT",
    "JUGE",
    "DECLARE",
    "STATUANT",
    "REJETTE",
    "CONFIRME",
    "INFIRME",
    "ANNULE",
    "CASSE",
    "RENVOIE",
    "COUR",
    "CHAMBRE",
    "AUDIENCE",
    "ARRET",
    "JUGEMENT",
    "DECISION",
    "ORDONNANCE",
    "CONCLUSIONS",
    "BORDEREAU",
    "REPUBLIQUE",
    "FRANCAISE",
    "ARTICLE",
    "CODE",
    "CIVIL",
    "PENAL",
    "PROCEDURE",
    "TRAVAIL",
    "COMMERCE",
    "PREMIER",
    "DEUXIEME",
    "TROISIEME",
    "TITRE",
    "CHAPITRE",
    "SECTION",
    "ALINEA",
    "PARAGRAPHE",
    "LOI",
    "DECRET",
    "ARRETE",
    "TEXTE",
    "DROIT",
    "FAIT",
    "FAITS",
    "OBJET",
    "EXPOSE",
    "MOTIF",
    "MOTIFS",
    "DISPOSITIF",
    "FOND",
}


def _is_company_stopword(text: str) -> bool:
    words = _norm_upper(text).split()

    if not words:
        return True

    return all(word in _COMPANY_STOPWORDS for word in words)


_SOCIETE_PATTERNS = [

    # SCI FONCIERE DU COQUELICOT
    re.compile(
        rf"\b"
        rf"(?P<forme>(?i:{_FORMES}))"
        rf"[ \t]+"
        rf"(?P<name>{_SOC_NAME})"
        rf"\b"
    ),

    # ABC ARCHITECTES SAS
    re.compile(
        rf"\b"
        rf"(?P<name>{_SOC_NAME})"
        rf"[ \t]+"
        rf"(?P<forme>(?i:{_FORMES}))"
        rf"\b"
    ),

    # La société ABC ARCHITECTES
    re.compile(
        rf"\b"
        rf"(?i:(?:la[ \t]+)?(?:société|societe|entreprise|"
        rf"association|fondation|mutuelle|caisse|banque|compagnie))"
        rf"[ \t]+"
        rf"(?P<name>{_SOC_NAME})"
        rf"\b"
    ),

    # Cabinet MARTIN
    re.compile(
        rf"\b"
        rf"(?i:Cabinet|Étude|Etude|Office)"
        rf"[ \t]+"
        rf"(?P<name>"
        rf"(?!D['’]AVOCATS?\b)"
        rf"{_SOC_NAME}"
        rf")"
        rf"\b"
    ),
]


def find_societes(text: str) -> list[RawMatch]:
    out: list[RawMatch] = []

    for pattern in _SOCIETE_PATTERNS:

        for match in pattern.finditer(text):

            name = match.group("name").strip()

            # Pour les sociétés dont la forme juridique est placée
            # après le nom : "ACME SARL", "DUPONT SAS", etc.
            forme = match.groupdict().get("forme")

            if forme and match.end("forme") == match.end():
                name = text[
                    match.start("name"):match.end("forme")
                ].strip()

            if len(name) < 2:
                continue

            if _is_company_stopword(name):
                continue

            normalized = _strip_accents(name).upper()

            if normalized in {
                "D'AVOCATS",
                "D AVOCATS",
                "D'AVOCAT",
                "D AVOCAT",
                "AVOCAT",
                "AVOCATS",
            }:
                continue

            out.append(
                RawMatch(
                    match.start("name"),
                    match.end("forme") if forme else match.end("name"),
                    name,
                    "PERSONNE_MORALE",
                    0.96,
                    "company_context",
                )
            )

    return _dedupe_overlaps(out)

# ============================================================================
# Noms de personnes
# ============================================================================

_CIVILITES = (
    r"Monsieur|Madame|Mme|Mlle|M\.|Me|"
    r"Maître|Dr|Docteur|Pr|Professeur"
)


_ROLES = (
    r"requérant(?:e)?|"
    r"défendeur(?:esse)?|"
    r"demandeur(?:esse)?|"
    r"appelant(?:e)?|"
    r"intimé(?:e)?|"
    r"prévenu(?:e)?|"
    r"accusé(?:e)?|"
    r"partie[ \t]+civile|"
    r"partie[ \t]+intervenante|"
    r"assignant(?:e)?|"
    r"assigné(?:e)?"
)


_NAME = (
    r"(?:"
    r"[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÿ'’\-]{1,30}"
    r"(?:"
    r"[ \t]+"
    r"[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÿ'’\-]{1,30}"
    r"){0,4}"
    r")"
)


_CONTEXTES = [
    rf"(?:{_CIVILITES})",
    rf"(?:le|la|les)[ \t]+(?:{_ROLES})",
    rf"\bl['’](?:{_ROLES})",
    r"(?:consorts|époux|épouse|veuve|héritiers[ \t]+de|aux[ \t]+droits[ \t]+de)",
]


_NAME_PATTERNS = [
    re.compile(
        rf"(?i:{ctx})[ \t]+({_NAME})"
    )
    for ctx in _CONTEXTES
]


# NOM Prénom
_NOM_MAJ = re.compile(
    r"\b"
    r"([A-ZÀ-ÖØ-Þ]{2,}(?:-[A-ZÀ-ÖØ-Þ]{2,})*)"
    r"[ \t]+"
    r"([A-ZÀ-ÖØ-Þ][a-zà-ÿ'’]{1,30}"
    r"(?:-[A-ZÀ-ÖØ-Þ][a-zà-ÿ'’]{1,30})*)"
    r"\b"
)


# Prénom NOM
_PRENOM_NOM = re.compile(
    r"\b"
    r"([A-ZÀ-ÖØ-Þ][a-zà-ÿ'’]{1,30}"
    r"(?:-[A-ZÀ-ÖØ-Þ][a-zà-ÿ'’]{1,30})*)"
    r"[ \t]+"
    r"([A-ZÀ-ÖØ-Þ]{2,}(?:-[A-ZÀ-ÖØ-Þ]{2,})*)"
    r"\b"
)


_NOT_FIRSTNAME = {
    "code",
    "article",
    "loi",
    "decret",
    "arrete",
    "ordonnance",
    "jugement",
    "arret",
    "decision",
    "audience",
    "tribunal",
    "cour",
    "chambre",
    "section",
    "titre",
    "chapitre",
    "livre",
    "partie",
    "annexe",
    "alinea",
    "paragraphe",
    "monsieur",
    "madame",
    "maitre",
    "docteur",
    "professeur",
    "vu",
    "attendu",
    "considerant",
    "statuant",
    "ordonne",
    "condamne",
    "rejette",
    "republique",
    "francaise",
    "etat",
    "ministre",
    "prefet",
    "maire",
    "janvier",
    "fevrier",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "aout",
    "septembre",
    "octobre",
    "novembre",
    "decembre",
}


_PERSON_STOPWORDS = {
    "CABINET",
    "AVOCAT",
    "AVOCATS",
    "FONDATEUR",
    "FONDATRICE",
    "TRIBUNAL",
    "PROXIMITE",
    "DOSSIER",
    "INSCRITE",
    "INSCRIT",
    "SOCIETE",
    "REPRESENTE",
    "REPRESENTEE",
    "ASSOCIE",
    "ASSOCIEE",
    "GERANT",
    "GERANTE",
    "SOCIAL",
    "DEA",
    "TELEPHONE",
    "TEL",
    "ARCHITECTES",
    "DROIT",
    "ARTICLE",
    "CHAMBRE",
    "CODE",
    "LOI",
    "DECRET",
    "ARRETE",
    "ORDONNANCE",
    "JUGEMENT",
    "ARRET",
    "DECISION",
    "AUDIENCE",
    "COUR",
    "SECTION",
    "TITRE",
    "CHAPITRE",
    "LIVRE",
    "PARTIE",
    "ANNEXE",
    "ALINEA",
    "PARAGRAPHE",
}


def _is_person_stopword(text: str) -> bool:
    words = _norm_upper(text).split()

    return bool(words) and all(
        word in _PERSON_STOPWORDS
        for word in words
    )


def find_person_names(text: str) -> list[RawMatch]:
    out: list[RawMatch] = []

    # Personnes avec contexte juridique
    for pattern in _NAME_PATTERNS:

        for match in pattern.finditer(text):

            name = match.group(1).strip()

            if len(name) < 3:
                continue

            if _is_person_stopword(name):
                continue

            out.append(
                RawMatch(
                    match.start(1),
                    match.end(1),
                    name,
                    "PERSONNE",
                    0.95,
                    "person_context",
                )
            )

    # NOM Prénom
    for match in _NOM_MAJ.finditer(text):

        nom = match.group(1)
        prenom = match.group(2)

        if _is_person_stopword(nom):
            continue

        if _strip_accents(prenom) in _NOT_FIRSTNAME:
            continue

        out.append(
            RawMatch(
                match.start(),
                match.end(),
                match.group(0),
                "PERSONNE",
                0.90,
                "surname_uppercase",
            )
        )

    # Prénom NOM
    for match in _PRENOM_NOM.finditer(text):

        prenom = match.group(1)
        nom = match.group(2)

        if _is_person_stopword(nom):
            continue

        if _strip_accents(prenom) in _NOT_FIRSTNAME:
            continue

        out.append(
            RawMatch(
                match.start(),
                match.end(),
                match.group(0),
                "PERSONNE",
                0.90,
                "firstname_surname_uppercase",
            )
        )

    return _dedupe_overlaps(out)


# ============================================================================
# Avocats
# ============================================================================

_AVOCAT = [

    re.compile(
        rf"\b(?i:Maître|Me)[ \t]+({_NAME})"
    ),

    re.compile(
        rf"\b(?i:avocat|avocate|conseil)"
        rf"[ \t]*:[ \t]*"
        rf"({_NAME})"
    ),
]

def find_avocats(text: str) -> list[RawMatch]:
    out: list[RawMatch] = []

    # Une forme juridique ne doit jamais être considérée comme
    # un nom d'avocat : SAS, SARL, SCI, etc.
    company_forms = {
        "SAS",
        "SASU",
        "SARL",
        "EURL",
        "SA",
        "SCI",
        "SCP",
        "SCM",
        "SNC",
        "GIE",
        "SELARL",
        "SELAS",
        "SEL",
        "SELAFA",
        "SELCA",
        "SCA",
        "SCIC",
        "SCOP",
        "GAEC",
        "EARL",
    }

    for pattern in _AVOCAT:

        for match in pattern.finditer(text):

            name = match.group(1).strip()

            # Une forme juridique seule n'est pas un avocat.
            if _strip_accents(name).upper() in company_forms:
                continue

            out.append(
                RawMatch(
                    match.start(1),
                    match.end(1),
                    name,
                    "AVOCAT",
                    0.98,
                    "avocat_context",
                )
            )

    return _dedupe_overlaps(out)

# ============================================================================
# Magistrats
# ============================================================================

_MAGISTRAT = [

    re.compile(
        rf"(?i:Madame|Monsieur|Mme|M\.)"
        rf"[ \t]+"
        rf"({_NAME})"
        rf"[ \t]+"
        rf"(?i:"
        rf"président|présidente|"
        rf"juge|magistrat|magistrate|"
        rf"conseiller|conseillère"
        rf")"
    ),

    re.compile(
        rf"(?i:"
        rf"président|présidente|"
        rf"juge|magistrat|magistrate|"
        rf"conseiller|conseillère"
        rf")"
        rf"[ \t]+"
        rf"({_NAME})"
    ),
]


def find_magistrats(text: str) -> list[RawMatch]:
    out: list[RawMatch] = []

    for pattern in _MAGISTRAT:

        for match in pattern.finditer(text):

            name = match.group(1).strip()

            out.append(
                RawMatch(
                    match.start(1),
                    match.end(1),
                    name,
                    "MAGISTRAT",
                    0.98,
                    "magistrat_context",
                )
            )

    return _dedupe_overlaps(out)


# ============================================================================
# Lieux
# ============================================================================

_CITY = (
    r"[A-ZÀ-ÖØ-ÞŸ]"
    r"[A-Za-zÀ-ÿ'’\-]{1,40}"
    r"(?:[ \-]"
    r"[A-ZÀ-ÖØ-ÞŸ]"
    r"[A-Za-zÀ-ÿ'’\-]{1,40}"
    r"){0,4}"
)


_LIEU_PATTERNS = [

    # né à Strasbourg
    re.compile(
        rf"(?i:n[ée])[ \t]+à[ \t]+({_CITY})"
        rf"(?=\s+(?:et|ou|le|la|les|qui|dans|depuis|en|au|aux)\b"
        rf"|[,.;)\n]|$)"
    ),

    # demeurant à Strasbourg
    re.compile(
        rf"(?i:"
        rf"demeurant|demeure|domicilié?|domiciliée|"
        rf"résidant|réside|habitant"
        rf")[ \t]+à[ \t]+({_CITY})"
        rf"(?=\s+(?:et|ou|le|la|les|qui|dans|depuis|en|au|aux)\b"
        rf"|[,.;)\n]|$)"
    ),

    # originaire de Strasbourg
    re.compile(
        rf"(?i:"
        rf"originaire|issu|issue"
        rf")[ \t]+de[ \t]+({_CITY})"
        rf"(?=\s+(?:et|ou|le|la|les|qui|dans|depuis|en|au|aux)\b"
        rf"|[,.;)\n]|$)"
    ),

    # ville de Strasbourg
    re.compile(
        rf"(?i:"
        rf"ville|commune"
        rf")[ \t]+de[ \t]+({_CITY})"
        rf"(?=\s+(?:et|ou|le|la|les|qui|dans|depuis|en|au|aux)\b"
        rf"|[,.;)\n]|$)"
    ),

    # nationalité française
    re.compile(
        r"(?:de[ \t]+nationalité)[ \t]+"
        r"([A-Za-zÀ-ÿ'-]{2,40})"
        r"(?=[,.;)\n]|$)",
        re.IGNORECASE,
    ),
]


def find_lieux(text: str) -> list[RawMatch]:
    out: list[RawMatch] = []

    for pattern in _LIEU_PATTERNS:

        for match in pattern.finditer(text):

            value = match.group(1).strip()

            if len(value) < 2:
                continue

            out.append(
                RawMatch(
                    match.start(1),
                    match.end(1),
                    value,
                    "LIEU",
                    0.90,
                    "place_context",
                )
            )

    return _dedupe_overlaps(out)


# ============================================================================
# Adresses
# ============================================================================

_STREET_TYPES = (
    r"rue|avenue|boulevard|allée|chemin|impasse|place|quai|cours|"
    r"route|square|villa|passage|lotissement|résidence|hameau|"
    r"lieu-?dit|voie|clos|sentier|promenade|esplanade|parvis|"
    r"faubourg"
)


_ADRESSE_VOIE_RE = re.compile(
    rf"(?<!\w)"
    rf"\d{{1,4}}"
    rf"(?:[ \t]?(?:bis|ter|quater))?"
    rf"[ \t]+"
    rf"(?:{_STREET_TYPES})\b"
    rf"[^,\n.;]{{0,60}}"
    rf"(?:"
    rf",[ \t]*\d{{5}}[ \t]+"
    rf"[A-ZÀ-ÖØ-ÞŸ]"
    rf"[A-Za-zÀ-ÿ'’\-]+"
    rf"(?:[ \t-]+"
    rf"[A-ZÀ-ÖØ-ÞŸ]"
    rf"[A-Za-zÀ-ÿ'’\-]+)"
    rf"{{0,3}}"
    rf")?",
    re.IGNORECASE,
)


def find_adresses(text: str) -> list[RawMatch]:
    out: list[RawMatch] = []

    for match in _ADRESSE_VOIE_RE.finditer(text):

        out.append(
            RawMatch(
                match.start(),
                match.end(),
                match.group(0),
                "ADRESSE",
                0.98,
                "address_regex",
            )
        )

    return _dedupe_overlaps(out)


# ADRESSE est également exposée via find_structured_pii(), attendu par les
# tests existants qui interrogent cette seule fonction pour les PII
# structurées.
_STRUCTURED.append(("ADRESSE", _ADRESSE_VOIE_RE, None, None, 0.93))


# ============================================================================
# Communes
# ============================================================================

_COMMON_COMMUNES = {
    "Paris",
    "Strasbourg",
    "Haguenau",
    "Colmar",
    "Mulhouse",
    "Lyon",
    "Marseille",
    "Bordeaux",
    "Toulouse",
    "Nantes",
    "Lille",
    "Nice",
    "Rennes",
    "Metz",
    "Nancy",
}


def find_communes(text: str) -> list[RawMatch]:
    out: list[RawMatch] = []

    for commune in _COMMON_COMMUNES:

        pattern = re.compile(
            rf"(?<!\w){re.escape(commune)}(?!\w)",
            re.IGNORECASE,
        )

        for match in pattern.finditer(text):

            out.append(
                RawMatch(
                    match.start(),
                    match.end(),
                    match.group(0),
                    "COMMUNE",
                    0.85,
                    "commune",
                )
            )

    return _dedupe_overlaps(out)


# ============================================================================
# Détection globale
# ============================================================================

def find_all(text: str) -> list[RawMatch]:
    """
    Lance toutes les familles de détection.

    Retourne une liste de RawMatch triée par position.
    """

    matches: list[RawMatch] = []

    matches.extend(find_structured_pii(text))
    matches.extend(find_juridictions(text))
    matches.extend(find_societes(text))
    matches.extend(find_person_names(text))
    matches.extend(find_avocats(text))
    matches.extend(find_magistrats(text))
    matches.extend(find_lieux(text))
    matches.extend(find_adresses(text))
    matches.extend(find_communes(text))

    return _dedupe_overlaps(matches)