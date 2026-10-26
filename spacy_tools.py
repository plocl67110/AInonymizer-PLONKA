"""
Outils pour la détection des entités nommées avec spaCy.

Compléments adaptés au français juridique :
- PER -> PERSONNE
- ORG -> PERSONNE_MORALE
- LOC/GPE -> LIEU
- DATE -> DATE
- MISC correspondant à une société -> PERSONNE_MORALE
- dates françaises non détectées par spaCy -> DATE

Modifications principales :
- chargement spaCy allégé et plus sûr ;
- scores de confiance différenciés par catégorie ;
- détection de sociétés corrigée avec frontières de mots ;
- listes de filtrage moins agressives ;
- dates françaises élargies ;
- filtre optionnel par seuil de confiance.
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


# ---------------------------------------------------------------------------
# Correspondance entre labels spaCy et catégories internes
# ---------------------------------------------------------------------------

_SPACY_TO_CATEGORY = {
    "PER": "PERSONNE",
    "PERSON": "PERSONNE",
    "ORG": "PERSONNE_MORALE",
    "LOC": "LIEU",
    "GPE": "LIEU",
    "DATE": "DATE",
}


# Scores de confiance différenciés.
# spaCy ne fournit pas de score fiable par entité : ces valeurs sont
# volontairement prudentes et doivent pouvoir être filtrées ensuite.
_CONFIDENCE_BY_CATEGORY = {
    "PERSONNE": 0.75,
    "PERSONNE_MORALE": 0.70,
    "LIEU": 0.70,
    "DATE": 0.90,
}


# Sigles pouvant être légitimes dans un nom de société ou une référence.
_ACRONYMES_AUTORISES = {
    "SA",
    "SAS",
    "SARL",
    "SNC",
    "SEL",
    "SELARL",
    "SCP",
    "EURL",
    "SCA",
    "SCI",
}


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def _normaliser(text: str) -> str:
    """
    Normalise une chaîne pour comparaison :
    - minuscules ;
    - suppression des accents ;
    - espaces multiples réduits ;
    - ponctuation de bord retirée.
    """
    texte = unicodedata.normalize("NFD", text.strip().casefold())
    texte = "".join(
        c for c in texte
        if unicodedata.category(c) != "Mn"
    )
    return " ".join(texte.split()).strip(" .,:;()[]")


# ---------------------------------------------------------------------------
# Labels, acronymes et civilités mal détectés par spaCy
# ---------------------------------------------------------------------------

_SPACY_STOPWORDS = {
    "iban",
    "siren",
    "siret",
    "nir",
    "rib",
    "tva",
    "kbis",
    "cerfa",
    "rcs",
    "urssaf",
    "cnil",
    "rgpd",
    "ref",
    "réf",
    "monsieur",
    "madame",
    "mademoiselle",
    "maître",
    "maitre",
    "docteur",
    "professeur",
    "avocat",
    "avocate",
    "avocats",
    "avocates",
    "magistrat",
    "magistrate",
    "magistrats",
    "magistrates",
    "m",
    "mme",
    "mlle",
    "pr",
    "dr",
    "annexe",
    "pièce",
    "piece",
}


def _is_spacy_stopword(text: str) -> bool:
    """
    Élimine les labels, acronymes et civilités isolées que spaCy peut
    étiqueter à tort comme entité nommée.
    """
    valeur = _normaliser(text)

    if valeur in _SPACY_STOPWORDS:
        return True

    mots = valeur.split()

    if not mots:
        return True

    premier = mots[0]
    reste = " ".join(mots[1:])

    # Exemples : "Annexe 9", "Pièce n°12", "Annexe n° 3".
    if premier in {"annexe", "pièce", "piece"} and re.fullmatch(
        r"(?:n[°o]?\s*)?\d+",
        reste,
    ):
        return True

    return False


# ---------------------------------------------------------------------------
# Bruit évident produit par spaCy ou l’OCR
# ---------------------------------------------------------------------------

_SPACY_NOISE = {
    "audience",
    "conclusions",
    "préjudice",
    "prejudice",
    "annexe",
    "section",
    "défendeur",
    "defendeur",
    "demande",
    "déclarer",
    "declarer",
    "proximité",
    "proximite",
    "fiche",
    "ttc",
}


def _is_spacy_noise(text: str) -> bool:
    """
    Élimine les fragments OCR, mots juridiques fréquents et acronymes
    très courts, sauf les sigles de sociétés explicitement autorisés.
    """
    valeur = _normaliser(text)

    if not valeur:
        return True

    if valeur in _SPACY_NOISE:
        return True

    compact = re.sub(r"[^A-Za-zÀ-ÿ]", "", text)

    # Fragments OCR ou tokens trop courts.
    if len(compact) <= 2:
        return True

    # Acronymes très courts, sauf sigles de sociétés autorisés.
    if (
        len(compact) <= 3
        and compact.isupper()
        and compact not in _ACRONYMES_AUTORISES
    ):
        return True

    return False


# ---------------------------------------------------------------------------
# Faux positifs juridiques / OCR observés
# ---------------------------------------------------------------------------

_SPACY_FALSE_POSITIVE_RE = re.compile(
    r"^(?:"
    r"annexe\s+\d+"
    r"|c\.\s+demande"
    r"|courriel\s+europ"
    r"|sur\s+l['’]"
    r"|l['’]absence"
    r"|qu['’]il"
    r"|puisqu['’]"
    r")$",
    re.IGNORECASE,
)


# Mots parfois mal classés par fr_core_news_sm.
# Les termes ambigus pouvant aussi être des noms propres — par exemple
# "Chambre", "Force", "Or", "Contre" — ne sont plus rejetés automatiquement.
_SPACY_LEGAL_WORDS = {
    "estimant",
    "passage",
    "fors",
    "celle",
    "omet",
    "bonne",
    "faux",
    "elfe",
    "eiles",
    "jui",
    "titre",
    "frais",
    "cesse",
}


_CONTEXTES_LEGITIMES = (
    "commune de",
    "mairie de",
    "société",
    "societe",
    "association",
    "entreprise",
    "cabinet",
    "monsieur",
    "madame",
    "m.",
    "mme",
)


def _is_spacy_false_positive(
    text: str,
    full_text: str,
    start: int,
    end: int,
) -> bool:
    """
    Élimine les faux positifs juridiques/OCR, sauf si un contexte
    légitime est présent à proximité.
    """
    valeur = _normaliser(text)

    if not valeur:
        return True

    if _SPACY_FALSE_POSITIVE_RE.match(valeur):
        return True

    if valeur not in _SPACY_LEGAL_WORDS:
        return False

    fenetre = full_text[
        max(0, start - 80):min(len(full_text), end + 80)
    ].casefold()

    return not any(
        contexte in fenetre
        for contexte in _CONTEXTES_LEGITIMES
    )


# Catégories pour lesquelles une entité légitime commence normalement
# par une majuscule.
_REQUIRES_CAPITAL = {
    "PERSONNE",
    "PERSONNE_MORALE",
    "LIEU",
}


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
    r"\b(?:"
    # 14 novembre 2026, 1er janvier 2026, 14 novembre
    r"\d{1,2}(?:er)?\s+(?:"
    + _MONTHS_FR +
    r")(?:\s+\d{4})?"
    r"|"
    # janvier 2026
    r"(?:"
    + _MONTHS_FR +
    r")\s+\d{4}"
    r"|"
    # 14/11/2026, 14-11-26
    r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}"
    r")\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Sociétés
# ---------------------------------------------------------------------------

_COMPANY_CONTEXT_RE = re.compile(
    r"(?:société|societe|entreprise|cabinet|association|"
    r"compagnie|groupe|établissement|etablissement|organisme)\s+$",
    re.IGNORECASE,
)


_COMPANY_SUFFIX_RE = re.compile(
    r"\b(?:SAS|SARL|SA|SNC|SEL|SELARL|SCP|EURL|SCA|SCI|CIE)\b",
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
    - société Martin & Cie
    - Martin & Cie SAS
    - Cabinet Durand
    """
    prefix = full_text[max(0, start - 60):start]

    if _COMPANY_CONTEXT_RE.search(prefix):
        return True

    return bool(_COMPANY_SUFFIX_RE.search(entity_text))


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
                exclude=[
                    "parser",
                    "tagger",
                    "attribute_ruler",
                    "lemmatizer",
                ],
            )
        except OSError as e:
            raise RuntimeError(
                "Modèle spaCy français non trouvé. "
                "Pour l'installer, exécutez :\n"
                "  python -m spacy download fr_core_news_sm\n"
                f"Erreur originale : {e}"
            ) from e
        except ValueError:
            # Certaines versions de spaCy n'acceptent pas "exclude"
            # pour tous les composants : repli sur "disable".
            _NLP = spacy.load(
                _MODEL_NAME,
                disable=[
                    "parser",
                    "tagger",
                    "attribute_ruler",
                    "lemmatizer",
                ],
            )

    return _NLP


# ---------------------------------------------------------------------------
# Détection
# ---------------------------------------------------------------------------

def find_spacy_entities(text: str) -> list[RawMatch]:
    """
    Détecte les entités nommées dans un texte français.

    spaCy est utilisé comme détecteur principal.
    Des règles complémentaires couvrent certaines dates françaises
    insuffisamment détectées par fr_core_news_sm.
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

        if _is_spacy_noise(ent.text):
            continue

        if _is_spacy_false_positive(
            ent.text,
            text,
            ent.start_char,
            ent.end_char,
        ):
            continue

        if category in _REQUIRES_CAPITAL and not _starts_with_capital(ent.text):
            continue

        matches.append(
            RawMatch(
                start=ent.start_char,
                end=ent.end_char,
                text=ent.text,
                category=category,
                confidence=_CONFIDENCE_BY_CATEGORY[category],
                source="spacy",
            )
        )

    # ------------------------------------------------------------------
    # 2. Dates françaises complémentaires
    # ------------------------------------------------------------------

    for match in _DATE_FR_RE.finditer(text):
        start = match.start()
        end = match.end()

        # Déjà détectée exactement par spaCy.
        if any(
            m.category == "DATE" and m.start == start and m.end == end
            for m in matches
        ):
            continue

        # Ne pas créer de chevauchement avec une autre entité.
        if any(
            start < existing.end and existing.start < end
            for existing in matches
        ):
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

    # Toujours retourner dans l’ordre du texte.
    return sorted(
        matches,
        key=lambda m: (m.start, m.end),
    )


# ---------------------------------------------------------------------------
# Filtre par seuil
# ---------------------------------------------------------------------------

def find_spacy_entities_filtered(
    text: str,
    seuil: float = 0.70,
) -> list[RawMatch]:
    """
    Retourne uniquement les entités dont la confiance est supérieure
    ou égale au seuil indiqué.

    Pour un usage juridique prudent, un seuil de 0,70 à 0,75 est un bon
    point de départ.
    """
    return [
        m
        for m in find_spacy_entities(text)
        if m.confidence >= seuil
    ]