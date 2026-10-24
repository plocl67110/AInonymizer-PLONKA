from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class IdentityKey:
    """Clé stable d'un candidat d'entité (conservée pour compatibilité)."""

    category_family: str
    normalized: str


class PseudoMap:
    """Table de pseudonymes partagée par tout le corpus.

    Règles d'identité :
    - un nom complet (« Julien MOREL ») identifie une personne ;
    - un nom de famille seul (« MOREL ») n'est rattaché à une personne existante
      que si celle-ci est la seule connue avec ce nom de famille ;
    - deux homonymes ne sont jamais fusionnés ;
    - un prénom seul n'est jamais rattaché à une personne.

    Préfixes :
    - avocats et magistrats gardent leur catégorie (AVOCAT_001, MAGISTRAT_001) ;
    - les autres personnes utilisent PERSONNE_NNN.
    """

    _CATEGORY_FAMILY = {
        "AVOCAT": "PERSONNE",
        "MAGISTRAT": "PERSONNE",
        "PERSONNE": "PERSONNE",
        "PERSONNE_MORALE": "PERSONNE_MORALE",
        "LIEU": "LIEU",
        "JURIDICTION": "JURIDICTION",
        "EMAIL": "EMAIL",
        "TEL": "TEL",
        "NIR": "NIR",
        "IBAN": "IBAN",
        "SIREN": "SIREN",
        "SIRET": "SIRET",
        "PLAQUE": "PLAQUE",
        "NUM_DOSSIER": "NUM_DOSSIER",
        "DATE": "DATE",
        "DATE_NAISSANCE": "DATE_NAISSANCE",
        "ADRESSE": "ADRESSE",
    }

    # Catégories dont le rôle est conservé dans le préfixe du pseudonyme.
    _VISIBLE_PREFIX = {"AVOCAT", "MAGISTRAT"}

    def __init__(self) -> None:
        self._identity_to_pseudo: dict[str, str] = {}
        self._pseudo_to_orig: dict[str, str] = {}
        self._pseudo_to_category: dict[str, str] = {}
        # Nom complet normalisé (ou nom de famille seul créé) -> identité
        self._person_identity: dict[str, str] = {}
        # Nom de famille -> identités des personnes connues avec ce nom
        self._surname_index: dict[str, set[str]] = {}
        self._counters: dict[str, int] = {}

    def assign(self, text: str, category: str) -> str:
        """Attribue un pseudonyme à un texte, selon sa catégorie."""
        family = self._family(category)
        normalized = self._normalize(text)

        if family != "PERSONNE":
            return self.assign_identity(f"{family}:{normalized}", text, category)

        identity = self._lookup_person(normalized)
        if identity is None:
            identity = self._create_person(normalized)
        return self.assign_identity(identity, text, category)

    def assign_identity(self, identity_id: str, text: str, category: str) -> str:
        """Attribue un pseudonyme à une identité déjà résolue."""
        if identity_id in self._identity_to_pseudo:
            return self._identity_to_pseudo[identity_id]

        family = self._family(category)
        prefix = category if category in self._VISIBLE_PREFIX else family
        n = self._counters.get(prefix, 0) + 1
        self._counters[prefix] = n
        pseudo = f"{prefix}_{n:03d}"

        self._identity_to_pseudo[identity_id] = pseudo
        self._pseudo_to_orig[pseudo] = text
        self._pseudo_to_category[pseudo] = category
        return pseudo

    def canonical_category(self, text: str) -> str | None:
        """Catégorie de la première occurrence de la personne, si elle est connue."""
        identity = self._lookup_person(self._normalize(text))
        if identity is None:
            return None
        pseudo = self._identity_to_pseudo.get(identity)
        if pseudo is None:
            return None
        return self._pseudo_to_category.get(pseudo)

    def to_dict(self) -> dict[str, str]:
        return dict(self._pseudo_to_orig)

    # ── Résolution des personnes ───────────────────────────────────────

    def _lookup_person(self, normalized: str) -> str | None:
        """Retrouve une identité sans en créer de nouvelle."""
        if normalized in self._person_identity:
            return self._person_identity[normalized]

        tokens = normalized.split()
        if len(tokens) == 1:
            candidates = self._surname_index.get(normalized, set())
            if len(candidates) == 1:
                return next(iter(candidates))

        return None

    def _create_person(self, normalized: str) -> str:
        """Crée une identité pour une forme jamais vue."""
        identity = f"PERSONNE:{normalized}"
        self._person_identity[normalized] = identity

        tokens = normalized.split()
        if len(tokens) >= 2:
            self._surname_index.setdefault(tokens[-1], set()).add(identity)

        return identity

    # ── Utilitaires ────────────────────────────────────────────────────

    def _family(self, category: str) -> str:
        return self._CATEGORY_FAMILY.get(category, category)

    @staticmethod
    def _normalize(text: str) -> str:
        text = unicodedata.normalize("NFC", text)
        text = text.casefold()
        text = text.replace("’", "'")
        text = re.sub(r"[-‐‑‒–—]", " ", text)
        text = text.replace("'", " ")
        text = " ".join(text.split())
        return text