> **AInonymizer-PLONKA est une version modifiée (fork) d'AInonymizer.** Le projet
> original, conçu par Florence Chatelot, est disponible sur
> [Miragide/AInonymizer](https://github.com/Miragide/AInonymizer).
> Les modifications décrites ci-dessous sont l'œuvre de Claude PLONKA et ne sont
> pas validées par l'autrice originale.

# AInonymizer — Outil d'anonymisation de PII

AInonymizer est un outil **local et headless** pour pseudonymiser des fichiers PDF, DOCX et Markdown.
Il détecte et remplace les **informations personnellement identifiables (PII)** par des pseudonymes,
tout en garantissant la **cohérence cross-document** (une même PII est toujours remplacée par le même pseudonyme).

---

## 🚀 Installation

### 1. Cloner le dépôt
```bash
git clone https://github.com/plocl67110/AInonymizer-PLONKA.git
cd ainonymizer

Ne pas considérer l'absence de match comme une preuve d'absence de PII : pour une utilisation
LLM, ajouter un scan résiduel et un statut `REVIEW_REQUIRED`.
