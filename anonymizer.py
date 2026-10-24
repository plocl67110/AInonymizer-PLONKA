"""
Pipeline d'anonymisation en 4 passes.
"""
from __future__ import annotations

import re

from dataclasses import dataclass

from juritools import (
    cross_reference_physico_morale,
    find_orthographic_variants,
    flag_doubtful_entities,
    propagate_multi_occurrences,
    reclassify_dates,
    trim_particles,
)
from pseudo_map import PseudoMap

from communes_fr import find_communes

from regex_fr import (
    RawMatch,
    find_adresses,
    find_avocats,
    find_juridictions,
    find_lieux,
    find_magistrats,
    find_person_names,
    find_societes,
    find_structured_pii,

)


# Intégration de spaCy pour la détection des entités nommées
from spacy_tools import find_spacy_entities


@dataclass
class Entity:
    start: int
    end: int
    text: str
    category: str
    pseudonym: str
    enabled: bool


# Catégories non substituées par défaut (délibération CNIL 01-057)
DEFAULT_DISABLED_CATEGORIES: frozenset[str] = frozenset(
    {"AVOCAT", "MAGISTRAT"}
)


# Priorité de déduplication (score plus haut = gagne en cas de chevauchement)
_PRIORITY: dict[str, float] = {
    "DATE_NAISSANCE": 10,
    "EMAIL": 10,

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

    # Une détection LIEU ne doit jamais écraser une personne
    # explicitement détectée par les règles spécialisées.
    "LIEU": 2,

    "PERSONNE": 3,
    "DATE": 1,
}

def _dedupe(matches: list[RawMatch]) -> list[RawMatch]:
    """
    Supprime les chevauchements en privilégiant l'entité la plus pertinente.

    Priorité :
      1. catégorie métier la plus prioritaire ;
      2. confiance ;
      3. longueur du match ;
      4. position dans le texte.

    Contrairement à une déduplication purement gauche-à-droite, cette
    stratégie permet par exemple à :

        "Maître Dupont" -> PERSONNE (spaCy)
        "Dupont"        -> AVOCAT   (regex spécialisée)

    de conserver AVOCAT, qui est la classification la plus précise.
    """

    candidates = sorted(
        matches,
        key=lambda m: (
            -_PRIORITY.get(m.category, 0),
            -m.confidence,
            -(m.end - m.start),
            m.start,
        ),
    )

    kept: list[RawMatch] = []

    for match in candidates:
        overlaps = any(
            match.start < existing.end
            and existing.start < match.end
            for existing in kept
        )

        if not overlaps:
            kept.append(match)

    kept.sort(key=lambda m: (m.start, m.end))

    return kept

def analyze(
    text: str,
    pseudo_map: PseudoMap,
    disabled_categories: frozenset[str] = DEFAULT_DISABLED_CATEGORIES,
) -> list[Entity]:
    """
    Analyse le texte et retourne la liste des entités avec leurs pseudonymes.

    pseudo_map est partagé entre tous les documents du corpus pour garantir
    la cohérence cross-document (même entité → même pseudonyme).

    disabled_categories est l'unique point de contrôle du statut
    activé/désactivé.
    """

    # ── Passe 1 : détection spécialisée ──────────────────────────────────
    #
    # Les détecteurs regex/domaines juridiques sont considérés comme
    # prioritaires pour les personnes. spaCy intervient ensuite comme
    # complément.
    specialized: list[RawMatch] = [
        *find_structured_pii(text),
        *find_adresses(text),
        *find_juridictions(text),
        *find_societes(text),
        *find_avocats(text),
        *find_magistrats(text),
        *find_person_names(text),
        *find_lieux(text),
        *find_communes(text),
    ]

    # ── Protection contre les faux LIEU de spaCy ─────────────────────────
    #
    # fr_core_news_sm peut classer à tort un nom de personne comme LIEU.
    # Exemple observé :
    #
    #   "M. Dupont"
    #        regex -> PERSONNE
    #        spaCy  -> LIEU
    #
    # Une détection spécialisée de personne doit donc protéger son span
    # contre une détection spaCy contradictoire en LIEU.
    spacy_matches = find_spacy_entities(text)

    # Les détecteurs spécialisés sont prioritaires sur spaCy.
    # Les dates spaCy restent autorisées comme complément.
    spacy_matches = [
        m
        for m in spacy_matches
        if m.category == "DATE"
        or not any(
            m.start < s.end and s.start < m.end
            for s in specialized
        )
    ]



    # Protection contre les faux PERSONNE_MORALE de spaCy.
    #
    # Exemple :
    #   "Orange du dossier" -> spaCy: PERSONNE_MORALE
    #
    # Les détections spécialisées restent prioritaires :
    #   "Orange SAS"
    #   "Orange SA"
    #   "société Orange"

    _AMBIGUOUS_COMPANY_NAMES = {
        "orange",
    }

    _COMPANY_CONTEXT_RE = re.compile(
        r"(?i)"
        r"(?:"
        r"\bsociété\s+|"
        r"\bsociete\s+|"
        r"\bentreprise\s+|"
        r"\bcabinet\s+|"
        r"\bassociation\s+|"
        r"\bcompagnie\s+|"
        r"\bgroupe\s+|"
        r"\bétablissement\s+|"
        r"\betablissement\s+|"
        r"\borganisme\s+"
        r")$"
    )

    filtered_spacy: list[RawMatch] = []

    for m in spacy_matches:
        if m.category != "PERSONNE_MORALE":
            filtered_spacy.append(m)
            continue

        normalized = m.text.casefold().strip()

        if normalized not in _AMBIGUOUS_COMPANY_NAMES:
            filtered_spacy.append(m)
            continue

        context_before = text[:m.start][-80:]

        explicit_company = bool(
            _COMPANY_CONTEXT_RE.search(context_before)
        )

        context_after = text[m.end:m.end + 40]

        explicit_company = explicit_company or bool(
            re.match(
                r"(?i)^\s+(?:SASU?|SARL|EURL|SA|SCI|SCP|SCM|SNC|GIE|"
                r"SELARL|SELAS|SEL|SELAFA|SELCA|SCA|SCIC|SCOP)\b",
                context_after,
            )
        )

        if explicit_company:
            filtered_spacy.append(m)
            continue

        # Nom ambigu sans contexte sociétaire :
        # laisser les détecteurs spécialisés décider.
        continue

    spacy_matches = filtered_spacy

    # Protection contre les faux LIEU spaCy correspondant à des communes
    # lexicalement ambiguës.
    #
    # Exemples :
    #   "Sens du jugement"  -> "Sens" n'est pas un lieu
    #   "Foix du dossier"   -> "Foix" n'est pas forcément un lieu
    #
    # En revanche :
    #   "à Sens"
    #   "à Foix"
    #   "demeurant aux Fins"
    #   "commune de Fins"
    # doivent rester détectés par communes_fr.

    ambiguous_communes = {
        "fins",
        "foix",
        "sens",
        "ville",
        "orange",
        "vienne",
        "bois",
        "cours",
        "fontaine",
        "fontaines",
        "mars",
        "avril",
        "mont",
        "pont",
        "saint",
        "val",
    }

    filtered_spacy: list[RawMatch] = []

    for m in spacy_matches:
        if m.category != "LIEU":
            filtered_spacy.append(m)
            continue

        normalized = m.text.casefold().strip()

        if normalized not in ambiguous_communes:
            filtered_spacy.append(m)
            continue

        context_before = text[:m.start][-80:]

        explicit_location = bool(
            re.search(
                r"(?i)"
                r"(?:"
                r"\b(?:à|a|au|aux|en|vers|depuis|dans|près de|près d')"
                r"|\b(?:commune|ville)\s+(?:de|du|des|d')"
                r"|\b(?:demeurant|demeure|domicilié|domiciliée|"
                r"résidant|réside|habitant)\s+(?:à|au|aux|en|dans)"
                r")"
                r"\s*$",
                context_before,
            )
        )

        if not explicit_location:
            continue

        filtered_spacy.append(m)

    spacy_matches = filtered_spacy
    protected_persons = [
        m
        for m in specialized
        if m.category in {"AVOCAT", "MAGISTRAT", "PERSONNE"}
    ]

    spacy_matches = [
        m
        for m in spacy_matches
        if not (
            m.category == "LIEU"
            and any(
                m.start < p.end and p.start < m.end
                for p in protected_persons
            )
        )
    ]

    raw: list[RawMatch] = [
        *specialized,
        *spacy_matches,
    ]

    # ── Passe 2 : post-traitement juritools ──────────────────────────────
    raw = reclassify_dates(text, raw)
    raw = flag_doubtful_entities(raw)
    raw = [*raw, *cross_reference_physico_morale(raw)]
    raw = [*raw, *propagate_multi_occurrences(text, raw)]
    raw = [*raw, *find_orthographic_variants(text, raw)]
    raw = trim_particles(text, raw)

    # ── Passe 3 : déduplication ─────────────────────────────────────────
    deduped = _dedupe(raw)

    # ── Passe 4 : assignation des pseudonymes ───────────────────────────
    #
    # Traité dans l'ordre du texte (deduped est trié par position) afin que
    # la première occurrence d'une entité fixe sa catégorie canonique.
    entities: list[Entity] = []

    for m in deduped:
        # La catégorie canonique (celle de la première occurrence de cette
        # entité, potentiellement dans un autre document du corpus) prime
        # sur la catégorie de CE match précis.
        #
        # Cela garantit qu'une même personne n'est jamais pseudonymisée
        # dans une occurrence et laissée en clair dans une autre au sein
        # du même document, et qu'elle ne reçoit jamais deux pseudonymes
        # différents.
        canonical_category = (
            pseudo_map.canonical_category(m.text) or m.category
        )

        pseudonym = pseudo_map.assign(
            m.text,
            canonical_category,
        )

        entities.append(
            Entity(
                start=m.start,
                end=m.end,
                text=m.text,
                category=m.category,
                pseudonym=pseudonym,
                enabled=canonical_category not in disabled_categories,
            )
        )

    entities.sort(key=lambda e: e.start)

    return entities


def apply_pseudonyms(
    text: str,
    entities: list[Entity],
) -> str:
    """Remplace les entités actives par leurs pseudonymes dans le texte."""
    enabled = sorted(
        (e for e in entities if e.enabled),
        key=lambda e: e.start,
    )

    parts: list[str] = []
    pos = 0

    for e in enabled:
        if e.start >= pos:
            parts.append(text[pos:e.start])
            parts.append(f"[{e.pseudonym}]")
            pos = e.end

    parts.append(text[pos:])

    return "".join(parts)





