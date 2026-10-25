"""
Pipeline d'anonymisation en 4 passes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace

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
    CATEGORY_PRIORITY,
    RawMatch,
    find_adresses,
    find_avocats,
    find_juridictions,
    find_lieux,
    find_magistrats,
    find_person_names,
    find_societes,
    find_structured_pii,
    filter_label_noise,
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


# Catégories non pseudonymisées par défaut (délibération CNIL 01-057)
DEFAULT_DISABLED_CATEGORIES: frozenset[str] = frozenset(
    {"AVOCAT", "MAGISTRAT"}
)


# Priorité de déduplication : table unique, définie dans regex_fr.py.
# Un LIEU ou une COMMUNE ne doit jamais écraser une personne détectée.
_PRIORITY: dict[str, float] = CATEGORY_PRIORITY


def _dedupe(matches: list[RawMatch]) -> list[RawMatch]:
    """
    Supprime les chevauchements en privilégiant l'entité la plus pertinente.

    Priorité :
      1. catégorie métier la plus prioritaire ;
      2. confiance ;
      3. longueur du match ;
      4. position dans le texte.

    Cette stratégie permet par exemple de conserver AVOCAT pour :

        "Maître Dupont" -> PERSONNE (spaCy)
        "Dupont"        -> AVOCAT   (regex spécialisée)
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
    la cohérence cross-document (même entité -> même pseudonyme).

    disabled_categories est l'unique point de contrôle du statut
    activé/désactivé.
    """

    # ── Passe 1 : détection spécialisée ─────────────────────────────────
    #
    # Les détecteurs regex et juridiques sont prioritaires pour les personnes.
    # spaCy intervient ensuite en complément.
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

    # ── Protection contre les faux LIEU et PERSONNE_MORALE de spaCy ─────
    #
    # fr_core_news_sm peut classer à tort un nom de personne comme LIEU :
    #   "M. Dupont" -> regex PERSONNE, spaCy LIEU
    # Un span détecté par un détecteur spécialisé est donc protégé contre
    # une détection spaCy contradictoire, sauf pour les dates.
    spacy_matches = find_spacy_entities(text)

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
    # Exemple : "Orange du dossier" -> spaCy PERSONNE_MORALE.
    # Un nom ambigu n'est conservé que s'il est précédé ou suivi d'un
    # contexte sociétaire explicite.

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

        # Nom ambigu sans contexte sociétaire : les détecteurs spécialisés
        # décident.
        continue

    spacy_matches = filtered_spacy

    # Protection contre les faux LIEU spaCy correspondant à des communes
    # lexicalement ambiguës.
    #
    # Exemples : "Sens du jugement", "Foix du dossier".
    # En revanche "à Sens", "à Foix", "commune de Fins" doivent rester
    # détectés par communes_fr.

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

    filtered_spacy = []

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

    raw = filter_label_noise(raw)

    # Une personne ne peut pas être découpée par une « personne morale » :
    # « ROUSSEL » dans « Marc ROUSSEL » est une partie de la personne, pas une société.
    # Un nom de famille seul qui correspond à une personne connue est traité comme
    # une personne, afin que la table de pseudonymes décide du rattachement.
    _PERSON_CATS = {"PERSONNE", "AVOCAT", "MAGISTRAT"}
    _persons = [m for m in raw if m.category in _PERSON_CATS]
    _surnames = {
        p.text.split()[-1] for p in _persons if len(p.text.split()) >= 2
    }

    _fixed: list[RawMatch] = []
    for m in raw:
        if m.category == "PERSONNE_MORALE":
            if any(p.start <= m.start and m.end <= p.end for p in _persons):
                continue
            if m.text.strip() in _surnames:
                m = replace(m, category="PERSONNE")
        _fixed.append(m)
    raw = _fixed

    # ── Passe 2 : post-traitement juritools ─────────────────────────────
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
    # Traité dans l'ordre du texte (deduped est trié par position) : la
    # première occurrence d'une entité fixe sa catégorie canonique.
    entities: list[Entity] = []

    for m in deduped:
        # La catégorie canonique (celle de la première occurrence, éventuellement
        # dans un autre document du corpus) prime sur la catégorie de ce match.
        #
        # Une même personne n'est ainsi jamais pseudonymisée dans une occurrence
        # et laissée en clair dans une autre, et ne reçoit jamais deux pseudonymes.
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