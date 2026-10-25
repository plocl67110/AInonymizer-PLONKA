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

    Règles d'identité des personnes :
    - un nom complet suivi d'une date de naissance identifie une personne ;
    - deux noms complets identiques avec des dates de naissance différentes
      désignent deux personnes distinctes ;
    - un nom complet sans date de naissance est rattaché à la seule personne
      connue sous ce nom ; s'il y en a plusieurs, il devient une nouvelle personne ;
    - un nom de famille seul est rattaché à la seule personne connue portant ce
      nom de famille ; sinon il devient une nouvelle personne ;
    - un prénom seul n'est jamais rattaché.

    Préfixes : avocats et magistrats gardent leur rôle (AVOCAT_001, MAGISTRAT_001).
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

    # Catégories dont le rôle reste visible dans le préfixe du pseudonyme.
    _VISIBLE_PREFIX = {"AVOCAT", "MAGISTRAT"}

    def __init__(self) -> None:
        self._identity_to_pseudo: dict[str, str] = {}
        self._pseudo_to_orig: dict[str, str] = {}
        self._pseudo_to_category: dict[str, str] = {}
        # identité -> date de naissance connue (None si inconnue)
        self._birth_of: dict[str, str | None] = {}
        # nom normalisé -> identités créées avec ce nom
        self._name_identities: dict[str, list[str]] = {}
        # nom de famille -> identités de personnes connues avec nom complet
        self._surname_index: dict[str, list[str]] = {}
        self._counters: dict[str, int] = {}

    # ── API publique ───────────────────────────────────────────────────

    def assign(self, text: str, category: str) -> str:
        """Attribue un pseudonyme selon la catégorie (sans date de naissance)."""
        family = self._family(category)
        if family != "PERSONNE":
            return self.assign_identity(
                f"{family}:{self._normalize(text)}", text, category
            )
        return self.assign_person(text, category)

    def assign_person(
        self,
        text: str,
        category: str,
        birth: str | None = None,
    ) -> str:
        """Attribue un pseudonyme à une personne, en tenant compte de sa date de naissance."""
        normalized = self._normalize(text)
        birth_key = self._normalize_birth(birth)
        identity = self._resolve_person(normalized, birth_key, mutate=True)
        if identity is None:
            identity = self._create_person(normalized, birth_key)
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

    def canonical_category(self, text: str, birth: str | None = None) -> str | None:
        """Catégorie de la première occurrence de la personne, si elle est connue."""
        identity = self._resolve_person(
            self._normalize(text),
            self._normalize_birth(birth),
            mutate=False,
        )
        if identity is None:
            return None
        pseudo = self._identity_to_pseudo.get(identity)
        if pseudo is None:
            return None
        return self._pseudo_to_category.get(pseudo)

    def to_dict(self) -> dict[str, str]:
        return dict(self._pseudo_to_orig)

    # ── Résolution des personnes ───────────────────────────────────────

    def _resolve_person(
        self,
        normalized: str,
        birth: str | None,
        mutate: bool,
    ) -> str | None:
        """Retrouve une identité existante, sans en créer de nouvelle."""
        tokens = normalized.split()
        if not tokens:
            return None

        known = self._name_identities.get(normalized, [])

        # Nom de famille seul, ou prénom seul
        if len(tokens) == 1:
            if len(known) == 1 and self._compatible(known[0], birth):
                return known[0]
            candidates = [
                c for c in self._surname_index.get(normalized, [])
                if self._compatible(c, birth)
            ]
            return candidates[0] if len(candidates) == 1 else None

        # Nom complet
        compatible = [c for c in known if self._compatible(c, birth)]

        if birth is None:
            return compatible[0] if len(compatible) == 1 else None

        exact = [c for c in compatible if self._birth_of.get(c) == birth]
        if exact:
            return exact[0]

        # Première occurrence avec date de naissance, pour une personne déjà vue
        # sans date : rattachement seulement s'il n'y a qu'une seule personne.
        
        return None

    def _compatible(self, identity: str, birth: str | None) -> bool:
        if birth is None:
            return True
        known_birth = self._birth_of.get(identity)
        return known_birth is None or known_birth == birth

    def _create_person(self, normalized: str, birth: str | None) -> str:
        """Crée une identité pour une personne jamais rattachée."""
        base = f"PERSONNE:{normalized}"
        if birth:
            base = f"{base}|{birth}"

        identity = base
        n = 2
        while identity in self._birth_of:
            identity = f"{base}#{n}"
            n += 1

        self._birth_of[identity] = birth
        self._name_identities.setdefault(normalized, []).append(identity)

        tokens = normalized.split()
        if len(tokens) >= 2:
            self._surname_index.setdefault(tokens[-1], []).append(identity)

        return identity

    # ── Utilitaires ────────────────────────────────────────────────────

    def _family(self, category: str) -> str:
        return self._CATEGORY_FAMILY.get(category, category)

    @staticmethod
    def _normalize_birth(birth: str | None) -> str | None:
        if not birth:
            return None
        return " ".join(birth.casefold().split())

    @staticmethod
    def _normalize(text: str) -> str:
        text = unicodedata.normalize("NFC", text)
        text = text.casefold()
        text = text.replace("’", "'")
        text = re.sub(r"[-‐‑‒–—]", " ", text)
        text = text.replace("'", " ")
        text = " ".join(text.split())
        return text