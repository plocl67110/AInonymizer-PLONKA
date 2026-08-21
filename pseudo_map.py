from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class IdentityKey:
    """Stable key for an entity candidate.

    IMPORTANT: text normalization is only a candidate key. The caller should
    resolve ambiguous same-name people using context/entity_id before calling
    assign(). This class deliberately avoids silently merging unrelated people.
    """
    category_family: str
    normalized: str


class PseudoMap:
    """Corpus-wide pseudonym map with conservative identity handling.

    The map keeps the legacy assign(text, category) API, but also exposes
    assign_identity() for callers that already resolved an entity identity.
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

    def __init__(self) -> None:
        self._identity_to_pseudo: dict[str, str] = {}
        self._pseudo_to_orig: dict[str, str] = {}
        self._pseudo_to_category: dict[str, str] = {}
        self._norm_to_identity: dict[tuple[str, str], str] = {}
        self._counters: dict[str, int] = {}

    def assign(self, text: str, category: str) -> str:
        """Legacy deterministic assignment.

        This remains safe for structured identifiers. For PERSONNE-like
        entities, callers should prefer assign_identity() after resolution.
        """
        family = self._family(category)
        normalized = self._normalize(text)

        # Structured values are safe to key by normalized value.
        if family != "PERSONNE":
            identity = f"{family}:{normalized}"
            return self.assign_identity(identity, text, category)

        # Legacy behavior for people: same exact normalized spelling remains
        # coherent. It must not be used as proof that two same-name people are
        # identical.
        key = (family, normalized)
        if key in self._norm_to_identity:
            return self._identity_to_pseudo[self._norm_to_identity[key]]

        identity = f"{family}:{normalized}"
        self._norm_to_identity[key] = identity
        return self.assign_identity(identity, text, category)

    def assign_identity(self, identity_id: str, text: str, category: str) -> str:
        """Assign a pseudonym to an already-resolved entity identity."""
        if identity_id in self._identity_to_pseudo:
            return self._identity_to_pseudo[identity_id]

        family = self._family(category)
        n = self._counters.get(family, 0) + 1
        self._counters[family] = n
        pseudo = f"{family}_{n:03d}"
        self._identity_to_pseudo[identity_id] = pseudo
        self._pseudo_to_orig[pseudo] = text
        self._pseudo_to_category[pseudo] = category
        return pseudo

    def canonical_category(self, text: str) -> str | None:
        normalized = self._normalize(text)
        for (family, value), identity in self._norm_to_identity.items():
            if value == normalized:
                pseudo = self._identity_to_pseudo.get(identity)
                if pseudo:
                    return self._pseudo_to_category.get(pseudo)
        return None

    def to_dict(self) -> dict[str, str]:
        return dict(self._pseudo_to_orig)

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
