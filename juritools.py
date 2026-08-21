"""
Outils juridiques pour l'anonymisation :
- Propagation des occurrences multiples
- Référencement croisé personne morale/personne physique
- Reclassification des dates
- Résolution des chevauchements entre entités
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import replace

from regex_fr import RawMatch

# Catégories à ne pas propager (car structurées et sensibles aux chevauchements)
_NO_PROPAGATE_CATS: frozenset[str] = frozenset({
    "EMAIL", "TEL", "NIR", "IBAN", "SIREN", "SIRET", "PLAQUE",
    "NUM_DOSSIER", "DATE", "DATE_NAISSANCE", "ADRESSE",
    # Ajout des catégories spaCy pour éviter leur propagation
    "spacy_PERSONNE", "spacy_PERSONNE_MORALE", "spacy_LIEU", "spacy_DATE",
})

# Catégories structurées (pour éviter la propagation)
_STRUCTURED_CATS: frozenset[str] = frozenset({
    "EMAIL", "IBAN", "NIR", "SIREN", "SIRET", "TEL", "PLAQUE",
    "NUM_DOSSIER", "DATE", "DATE_NAISSANCE",
})

# Particules à supprimer des noms (ex: "le", "la", "de")
_PARTICLES = {
    "le", "la", "les", "l", "un", "une", "des", "de", "du", "d",
    "a", "au", "aux", "en", "par", "pour", "sur", "sous", "dans",
    "avec", "sans", "chez", "vers", "depuis", "entre", "et", "ou",
    "mais", "ni", "car", "or", "donc",
}

def propagate_multi_occurrences(text: str, matches: list[RawMatch]) -> list[RawMatch]:
    """
    Propage les occurrences multiples des entités non structurées avec une confiance élevée.
    Les entités structurées (ex: NIR, IBAN) sont exclues pour éviter les chevauchements dangereux.
    """
    by_key: dict[tuple[str, str], tuple[str, str]] = {}
    for m in matches:
        if m.category in _NO_PROPAGATE_CATS:
            continue
        if getattr(m, "confidence", 1.0) < 0.90:
            continue
        key = (m.category, _normalize(m.text))
        by_key.setdefault(key, (m.category, m.text))

    existing = {(m.start, m.end) for m in matches}
    added: list[RawMatch] = []

    for category, needle in by_key.values():
        if len(_normalize(needle)) < 3:
            continue
        pattern = re.compile(
            r"(?<!\w)" + re.escape(needle) + r"(?!\w)",
            re.IGNORECASE,
        )
        for m in pattern.finditer(text):
            span = (m.start(), m.end())
            if span in existing:
                continue
            existing.add(span)
            added.append(RawMatch(
                start=m.start(), end=m.end(), text=m.group(0),
                category=category, confidence=0.90, source="propagation",
            ))
    return added

def cross_reference_physico_morale(matches: list[RawMatch]) -> list[RawMatch]:
    """
    Détecte les noms de personnes dans les noms de sociétés (ex: "Martin" dans "Société Martin & Cie").
    """
    # Inclure les entités détectées par spaCy
    person_names = [
        m for m in matches
        if m.category in ("PERSONNE", "AVOCAT", "MAGISTRAT", "spacy_PERSONNE")
        and getattr(m, "confidence", 1.0) >= 0.90
    ]
    societes = [m for m in matches if m.category in ("PERSONNE_MORALE", "spacy_PERSONNE_MORALE")]
    added: list[RawMatch] = []

    for soc in societes:
        for person in person_names:
            name = person.text.strip()
            if len(name) < 3:
                continue
            match = re.search(
                r"(?<!\w)" + re.escape(name) + r"(?!\w)",
                soc.text,
                re.IGNORECASE,
            )
            if not match:
                continue
            abs_start = soc.start + match.start()
            abs_end = soc.start + match.end()
            if abs_start == soc.start and abs_end == soc.end:
                continue
            added.append(RawMatch(
                start=abs_start, end=abs_end,
                text=soc.text[match.start():match.end()],
                category="PERSONNE",
                confidence=0.94,
                source="cross_reference",
            ))
    return added

def _normalize(s: str) -> str:
    """Normalise une chaîne pour comparaison (sans accents, minuscules, espaces normalisés)."""
    s = unicodedata.normalize("NFC", s).casefold()
    return " ".join(s.split())

def _is_particle(word: str) -> bool:
    """Vérifie si un mot est une particule à supprimer."""
    cleaned = word.replace("'", "").replace("’", "").strip()
    norm = "".join(
        c for c in unicodedata.normalize("NFD", cleaned.casefold())
        if unicodedata.category(c) != "Mn"
    )
    return norm in _PARTICLES

# Regex pour détecter les particules en début ou fin de nom
_HEAD_RE = re.compile(r"^([A-Za-zÀ-ÿ]+['’]?)[\s,]+")
_TAIL_RE = re.compile(r"[\s,]+([A-Za-zÀ-ÿ]+['’]?)$")

def trim_particles(text: str, matches: list[RawMatch]) -> list[RawMatch]:
    """
    Supprime les particules (ex: "le", "la", "de") des noms de personnes ou sociétés.
    """
    result: list[RawMatch] = []

    for m in matches:
        if m.category in _STRUCTURED_CATS:
            result.append(m)
            continue

        start, end = m.start, m.end
        current = text[start:end]

        # Supprimer les particules en début de nom
        changed = True
        while changed and start < end:
            changed = False
            head = _HEAD_RE.match(current)
            if head and _is_particle(head.group(1)):
                candidate = current[len(head.group(0)):]
                if len(candidate.strip().split()) >= 2:
                    start += len(head.group(0))
                    current = text[start:end]
                    changed = True

        # Supprimer les particules en fin de nom
        changed = True
        while changed and start < end:
            changed = False
            tail = _TAIL_RE.search(current)
            if tail and _is_particle(tail.group(1)):
                candidate = current[:tail.start()]
                if len(candidate.strip().split()) >= 2:
                    end -= len(tail.group(0))
                    current = text[start:end]
                    changed = True

        trimmed = current.strip()
        if not trimmed:
            continue

        # Ajuster les positions pour les espaces de début/fin
        lead = len(current) - len(current.lstrip())
        trail = len(current) - len(current.rstrip())
        result.append(replace(
            m, start=start + lead, end=end - trail, text=trimmed
        ))

    return result

# Contexte pour les dates procédurales (à conserver en clair)
_PROC_CTX = re.compile(
    r"(?:audience\s+du|arr[eê]t\s+du|rendu\s+le|prononc[ée]\s+le"
    r"|pourvoi\s+form[ée]\s+le|signifi[ée]\s+le|notifi[ée]\s+le"
    r"|enregistr[ée]\s+le|d[ée]pos[ée]\s+le|re[çc]u\s+le|dat[ée]\s+du"
    r"|en\s+date\s+du)\s*[:,]?\s*$",
    re.IGNORECASE,
)

# Contexte pour les dates de naissance/décès (à anonymiser)
_BIRTH_CTX = re.compile(
    r"(?:n[ée]{1,2}\s+le|date\s+de\s+naissance|[âa]g[ée]{1,2}\s+de)\s*[:,]?\s*$",
    re.IGNORECASE,
)
_DEATH_CTX = re.compile(
    r"(?:d[ée]c[ée]d[ée]{1,2}\s+le|date\s+(?:du\s+)?d[ée]c[èe]s)\s*[:,]?\s*$",
    re.IGNORECASE,
)

def flag_doubtful_entities(matches: list[RawMatch]) -> list[RawMatch]:
    """
    Filtre les entités manifestement douteuses.

    Les noms très courts de 2 caractères peuvent être de vrais patronymes
    (ex. Li), tandis qu'une initiale isolée d'un seul caractère est ignorée.
    """
    result: list[RawMatch] = []

    for m in matches:
        text = m.text.strip()

        if not text:
            continue

        # Une seule lettre : initiale isolée, donc trop ambiguë.
        if len(text) == 1 and text.isalpha():
            continue

        result.append(m)

    return result

def reclassify_dates(text: str, matches: list[RawMatch]) -> list[RawMatch]:
    """
    Reclasse les dates en DATE_NAISSANCE si elles sont dans un contexte de naissance/décès.
    Les dates procédurales sont conservées en clair.
    """
    result: list[RawMatch] = []
    for m in matches:
        if m.category not in ("DATE", "spacy_DATE"):
            result.append(m)
            continue
        ctx = text[max(0, m.start - 120):m.start]
        if _BIRTH_CTX.search(ctx) or _DEATH_CTX.search(ctx):
            result.append(RawMatch(
                m.start, m.end, m.text, "DATE_NAISSANCE",
                getattr(m, "confidence", 1.0), getattr(m, "source", "context"),
            ))
        elif _PROC_CTX.search(ctx):
            # Les dates procédurales sont intentionnellement conservées en clair
            continue
        else:
            result.append(m)
    return result

def flag_doubtful_entities(matches: list[RawMatch]) -> list[RawMatch]:
    """
    Filtre les entités manifestement douteuses.

    Une initiale isolée d'un seul caractère est ignorée.
    Les noms courts de deux caractères restent valides
    (ex. « Li »).
    """
    result: list[RawMatch] = []

    for m in matches:
        value = m.text.strip()

        if not value:
            continue

        if len(value) == 1 and value.isalpha():
            continue

        result.append(m)

    return result


def resolve_overlaps(matches: list[RawMatch]) -> list[RawMatch]:
    """
    Résout les chevauchements entre entités en utilisant un système de priorités.
    Les entités avec une priorité plus élevée ou une confiance plus grande sont conservées.
    """
    # Priorités pour chaque catégorie (plus élevé = priorité plus forte)
    priority = {
        # Entités structurées (priorité maximale)
        "IBAN": 100, "NIR": 100, "EMAIL": 100, "TEL": 95,
        "SIRET": 95, "SIREN": 95, "PLAQUE": 95, "NUM_DOSSIER": 95,
        # Dates de naissance (priorité élevée)
        "DATE_NAISSANCE": 90,
        # Adresses et lieux
        "ADRESSE": 80,
        # Personnes morales et entités juridiques
        "PERSONNE_MORALE": 75, "AVOCAT": 70, "MAGISTRAT": 70, "JURIDICTION": 70,
        # Personnes physiques
        "PERSONNE": 65,
        # Lieux et dates générales
        "LIEU": 50, "DATE": 40,
        # Entités détectées par spaCy (priorité légèrement inférieure)
        "spacy_PERSONNE_MORALE": 70,
        "spacy_PERSONNE": 60,
        "spacy_LIEU": 45,
        "spacy_DATE": 35,
    }

    # Trier les entités par priorité (décroissante), confiance (décroissante), longueur (décroissante), puis position
    ordered = sorted(
        matches,
        key=lambda m: (
            -priority.get(m.category, 0),  # Priorité plus élevée en premier
            -getattr(m, "confidence", 1.0),  # Confiance plus élevée en premier
            -(m.end - m.start),              # Longueur plus grande en premier
            m.start,                         # Position plus tôt en premier
        ),
    )

    accepted: list[RawMatch] = []
    for candidate in ordered:
        # Vérifier si la candidate chevauche une entité déjà acceptée
        if any(
            candidate.start < a.end and a.start < candidate.end
            for a in accepted
        ):
            continue
        accepted.append(candidate)

    # Retourner les entités acceptées, triées par position
    return sorted(accepted, key=lambda m: (m.start, m.end))

def find_orthographic_variants(
    text: str,
    matches: list[RawMatch],
) -> list[RawMatch]:
    """
    Détecte les variantes orthographiques simples des entités déjà connues.

    Une variante est recherchée en tolérant :
    - les différences de casse ;
    - les espaces multiples ;
    - le remplacement d'un espace par un tiret ou inversement.

    Les entités structurées sont volontairement exclues.
    """
    if not text or not matches:
        return []

    existing = {(m.start, m.end) for m in matches}
    added: list[RawMatch] = []

    for source in matches:
        if source.category in _STRUCTURED_CATS:
            continue

        value = source.text.strip()
        if len(value) < 2:
            continue

        # Découper en mots pour pouvoir tolérer espace/tiret.
        words = [w for w in re.split(r"[\s\-]+", value) if w]
        if not words:
            continue

        # Un seul mot : la propagation classique s'en charge déjà.
        if len(words) == 1:
            continue

        # Entre les mots, accepter espaces ou tirets.
        separator = r"[\s\-]+"

        pattern = r"(?<!\w)" + separator.join(
            re.escape(word) for word in words
        ) + r"(?!\w)"

        regex = re.compile(pattern, re.IGNORECASE)

        for found in regex.finditer(text):
            span = (found.start(), found.end())

            # L'occurrence originale est déjà connue.
            if span in existing:
                continue

            existing.add(span)

            added.append(
                RawMatch(
                    start=found.start(),
                    end=found.end(),
                    text=found.group(0),
                    category=source.category,
                    confidence=min(
                        getattr(source, "confidence", 1.0),
                        0.92,
                    ),
                    source="orthographic_variant",
                )
            )

    return added