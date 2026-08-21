"""
Outils pour la détection des entités nommées avec spaCy.

Compléments adaptés au français juridique :
- PER -> PERSONNE
- ORG -> PERSONNE_MORALE
- LOC/GPE -> LIEU
- DATE -> DATE
- MISC correspondant à une société -> PERSONNE_MORALE
- dates françaises non détectées par spaCy -> DATE
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

import spacy

from regex_fr import RawMatch


_MODEL_NAME = "fr_core_news_sm"

# Modèle spaCy chargé une seule fois.
_NLP: Optional[spacy.Language] = None


_SPACY_TO_CATEGORY = {
    "PER": "PERSONNE",
    "PERSON": "PERSONNE",

    "ORG": "PERSONNE_MORALE",

    "LOC": "LIEU",
    "GPE": "LIEU",

    "DATE": "DATE",
}

# Labels/acronymes administratifs et civilités isolées que le petit modèle
# fr_core_news_sm étiquette parfois à tort comme entité nommée, en général
# quand ils précèdent (et non chevauchent) la vraie valeur structurée
# (ex: "IBAN : FR76..." -> "IBAN" seul taggé LIEU). Comparaison faite sur
# le texte normalisé (accents retirés, casse ignorée, point final ignoré).
_SPACY_STOPWORDS = {
    "iban", "siren", "siret", "nir", "rib", "tva", "rg", "kbis", "cerfa",
    "rcs", "urssaf", "cnil", "rgpd", "ntic", "n", "no", "ref",
    "monsieur", "madame", "mademoiselle", "maitre", "docteur",
    "professeur", "avocat", "avocats", "avocate", "avocates",
    "magistrat", "magistrate", "magistrats", "magistrates",
    "m", "mme", "mlle", "pr", "dr",
    # Mots capitalisés (début de phrase, titre de section, référence de
    # pièce) que le modèle confond parfois avec un nom propre — repérés
    # sur des documents juridiques OCRisés réels.
    "audience", "annexe", "piece", "or", "force", "chambre", "prejudice",
    "proximite", "contre",
}


def _is_spacy_stopword(text: str) -> bool:
    normalized = "".join(
        c for c in unicodedata.normalize("NFD", text.strip().casefold())
        if unicodedata.category(c) != "Mn"
    ).rstrip(".:")
    if normalized in _SPACY_STOPWORDS:
        return True
    # Variante avec un numéro à la suite (ex: "Annexe 9", "Pièce n°12").
    first_word = re.split(r"\s+", normalized, maxsplit=1)[0]
    rest = normalized[len(first_word):].strip()
    if first_word in _SPACY_STOPWORDS and re.fullmatch(r"(?:n[°o]?\s*)?\d+", rest):
        return True
    return False


# ---------------------------------------------------------------------------
# Bruit évident produit par spaCy (fragments courts, acronymes, titres)
# ---------------------------------------------------------------------------

_SPACY_NOISE = {
    "audience", "conclusions", "préjudice", "prejudice", "annexe",
    "section", "défendeur", "defendeur", "demande", "déclarer",
    "declarer", "proximité", "proximite", "fiche", "ttc",
}


def _is_spacy_noise(text: str) -> bool:
    """
    Élimine certains faux positifs évidents de fr_core_news_sm : mots
    juridiques/titres connus, acronymes très courts (TTC), et fragments
    de 1-2 caractères issus de l'OCR.
    """
    normalized = " ".join(text.casefold().split()).strip(" .,:;()[]")

    if not normalized:
        return True

    if normalized in _SPACY_NOISE:
        return True

    compact = re.sub(r"[^A-Za-zÀ-ÿ]", "", text)

    # Acronymes très courts comme TTC.
    if len(compact) <= 3 and compact.isupper():
        return True

    # Fragments OCR ou tokens trop courts.
    if len(compact) <= 2:
        return True

    return False


# ---------------------------------------------------------------------------
# Faux positifs juridiques / OCR observés sur des documents réels
# ---------------------------------------------------------------------------

_SPACY_FALSE_POSITIVE_RE = re.compile(
    r"^(?:"
    r"annexe\s+\d+"
    r"|c\.\s+demande"
    r"|courriel\s+europ"
    r"|sur\s+l['’]"
    r"|l['’]absence"
    r"|qu['’]’il"
    r"|puisqu['’]"
    r")$",
    re.IGNORECASE,
)

# Mots courants / juridiques que le petit modèle peut classer à tort comme
# PERSONNE ou LIEU. Cette liste correspond aux faux positifs observés sur
# des documents OCR de référence (beaucoup sont aussi de vraies communes
# françaises — voir le filtre équivalent, plus général, dans communes_fr.py).
_SPACY_LEGAL_WORDS = {
    "contre", "estimant", "passage", "fors", "celle", "grave", "omet",
    "bonne", "force", "faux", "elfe", "eiles", "jui", "four", "ondes",
    "chambre", "titre", "frais", "cesse",
}


def _is_spacy_false_positive(text: str) -> bool:
    """Élimine des faux positifs juridiques/OCR explicitement identifiés."""
    value = " ".join(text.casefold().split()).strip(" .,:;()[]")

    if not value:
        return True

    if _SPACY_FALSE_POSITIVE_RE.match(value):
        return True

    if value in _SPACY_LEGAL_WORDS:
        return True

    return False


# Catégories pour lesquelles un vrai nom propre français commence toujours
# par une majuscule. Sur du texte OCR bruité, le petit modèle fr_core_news_sm
# hallucine fréquemment des entités sur des mots minuscules ordinaires
# (pronoms, adjectifs, verbes...) — cette contrainte élimine cette classe
# entière de faux positifs sans toucher DATE, qui n'a pas cette propriété.
_REQUIRES_CAPITAL = {"PERSONNE", "PERSONNE_MORALE", "LIEU"}


def _starts_with_capital(text: str) -> bool:
    stripped = text.strip().lstrip("(\"'«’‘")
    return bool(stripped) and stripped[0].isupper()


# ---------------------------------------------------------------------------
# Dates françaises
# ---------------------------------------------------------------------------

_MONTHS_FR = (
    r"janvier|février|fevrier|mars|avril|mai|juin|"
    r"juillet|août|aout|septembre|octobre|novembre|"
    r"décembre|decembre"
)

_DATE_FR_RE = re.compile(
    rf"\b"
    rf"(?:"
    rf"\d{{1,2}}\s+(?:{_MONTHS_FR})\s+\d{{4}}"
    rf"|"
    rf"\d{{1,2}}[/-]\d{{1,2}}[/-]\d{{2,4}}"
    rf")"
    rf"\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Sociétés
# ---------------------------------------------------------------------------

_COMPANY_CONTEXT_RE = re.compile(
    r"(?:"
    r"société\s+|"
    r"societe\s+|"
    r"entreprise\s+|"
    r"cabinet\s+|"
    r"association\s+|"
    r"compagnie\s+|"
    r"groupe\s+|"
    r"établissement\s+|"
    r"etablissement\s+|"
    r"organisme\s+"
    r")$",
    re.IGNORECASE,
)


def _looks_like_company(
    entity_text: str,
    full_text: str,
    start: int,
) -> bool:
    """
    Détermine si une entité MISC est vraisemblablement une société.

    Exemples :
        société Martin & Cie
        Martin & Cie SAS
        Martin & Cie
    """

    prefix = full_text[max(0, start - 50):start]

    # "société Martin & Cie"
    if _COMPANY_CONTEXT_RE.search(prefix):
        return True

    upper = entity_text.upper()

    # Formes / indices fréquents dans les noms de sociétés.
    company_markers = (
        "& CIE",
        " CIE",
        " SAS",
        " SARL",
        " SA",
        " SNC",
        " SEL",
        " SELARL",
        " SCP",
        " EURL",
        " SCA",
    )

    return any(marker in upper for marker in company_markers)


# ---------------------------------------------------------------------------
# Chargement spaCy
# ---------------------------------------------------------------------------

def get_nlp() -> spacy.Language:
    """
    Charge et retourne le modèle spaCy français.

    Le modèle est chargé une seule fois.
    """

    global _NLP

    if _NLP is None:
        try:
            _NLP = spacy.load(
                _MODEL_NAME,
                disable=["parser", "tagger"],
            )

            # spaCy 3.8 expose "core_news_sm" dans meta["name"],
            # alors que le package installé est fr_core_news_sm.
            #
            # Le projet utilise le nom complet du modèle.
            _NLP.meta["name"] = _MODEL_NAME

        except OSError as e:
            raise RuntimeError(
                "Modèle spaCy français non trouvé. "
                "Pour l'installer, exécutez :\n"
                "  python -m spacy download fr_core_news_sm\n"
                f"Erreur originale : {e}"
            ) from e

    return _NLP


# ---------------------------------------------------------------------------
# Détection
# ---------------------------------------------------------------------------

def find_spacy_entities(text: str) -> list[RawMatch]:
    """
    Détecte les entités nommées dans le texte.

    SpaCy est utilisé comme détecteur principal.
    Des règles complémentaires couvrent certains cas français
    insuffisamment détectés par fr_core_news_sm.
    """

    nlp = get_nlp()
    doc = nlp(text)

    matches: list[RawMatch] = []

    # ------------------------------------------------------------------
    # 1. Entités spaCy
    # ------------------------------------------------------------------

    for ent in doc.ents:
        label = ent.label_

        category = _SPACY_TO_CATEGORY.get(label)

        # Le modèle français sm classe parfois une société en MISC.
        if category is None and label == "MISC":
            if _looks_like_company(
                ent.text,
                text,
                ent.start_char,
            ):
                category = "PERSONNE_MORALE"

        if category is None:
            continue

        if _is_spacy_stopword(ent.text):
            continue

        # Bruit juridique / OCR évident (acronymes courts, fragments...).
        if _is_spacy_noise(ent.text):
            continue

        # Faux positifs juridiques/OCR explicitement observés.
        if _is_spacy_false_positive(ent.text):
            continue

        if category in _REQUIRES_CAPITAL and not _starts_with_capital(ent.text):
            continue

        matches.append(
            RawMatch(
                start=ent.start_char,
                end=ent.end_char,
                text=ent.text,
                category=category,
                confidence=0.95,
                source="spacy",
            )
        )

    # ------------------------------------------------------------------
    # 2. Dates françaises complémentaires
    # ------------------------------------------------------------------

    existing_date_spans = {
        (m.start, m.end)
        for m in matches
        if m.category == "DATE"
    }

    for match in _DATE_FR_RE.finditer(text):
        start = match.start()
        end = match.end()

        # Déjà détectée par spaCy.
        if (start, end) in existing_date_spans:
            continue

        # Ne pas créer de chevauchement avec une autre entité.
        overlaps = any(
            start < existing.end and existing.start < end
            for existing in matches
        )

        if overlaps:
            continue

        matches.append(
            RawMatch(
                start=start,
                end=end,
                text=match.group(0),
                category="DATE",
                confidence=0.90,
                source="date_regex",
            )
        )

    # Toujours retourner dans l'ordre du texte.
    return sorted(
        matches,
        key=lambda m: (m.start, m.end),
    )