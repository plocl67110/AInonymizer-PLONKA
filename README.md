# Version durcie du moteur PII

Fichiers :
- `regex_fr.py` : détection structurée/contextuelle, confiance et bornes plus strictes.
- `juritools.py` : résolution des chevauchements, contexte de dates, propagation prudente.
- `pseudo_map.py` : normalisation Unicode et API `assign_identity()` pour séparer identité et texte.

## Point important

`PseudoMap.assign(text, category)` reste compatible avec l'ancienne API, mais pour les personnes
ayant le même nom, la vraie résolution d'identité doit être faite en amont avec `assign_identity()`.

Exemple :
```python
pseudo.assign_identity("PERSONNE:E-00017", "Jean Dupont", "PERSONNE")
pseudo.assign_identity("PERSONNE:E-00042", "Jean Dupont", "PERSONNE")
```

Cela permet deux personnes homonymes sans fusion silencieuse.

## Intégration

Après collecte de toutes les fonctions `find_*`, appliquer :
1. `reclassify_dates`
2. `trim_particles`
3. `resolve_overlaps`
4. `propagate_multi_occurrences`

# AInonymizer — Outil d'anonymisation de PII

AInonymizer est un outil **local et headless** pour pseudonymiser des fichiers PDF, DOCX et Markdown.
Il détecte et remplace les **informations personnellement identifiables (PII)** par des pseudonymes,
tout en garantissant la **cohérence cross-document** (une même PII est toujours remplacée par le même pseudonyme).

---

## 🚀 Installation

### 1. Cloner le dépôt
```bash
git clone https://github.com/votre-depot/ainonymizer.git
cd ainonymizer

Ne pas considérer l'absence de match comme une preuve d'absence de PII : pour une utilisation
LLM, ajouter un scan résiduel et un statut `REVIEW_REQUIRED`.
