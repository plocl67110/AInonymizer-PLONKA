# AInonymizer-PLONKA

> **AInonymizer-PLONKA est une version modifiée (fork) d'AInonymizer.** Le projet original, conçu par Florence Chatelot, est disponible sur [Miragide/AInonymizer](https://github.com/Miragide/AInonymizer). Les modifications décrites ci-dessous sont l'œuvre de Claude PLONKA et ne sont pas validées par l'autrice originale.

Pseudonymiseur local : retirez les données personnelles de vos documents avant de les soumettre à un LLM. Le traitement se fait sur votre poste, sans envoi de vos documents vers un service extérieur.

## Pourquoi cet outil ?

Les LLM (ChatGPT, Claude, Gemini…) sont utiles pour analyser des contrats, des dossiers ou des courriers, mais leur envoi peut exposer des données personnelles. AInonymizer détecte ces données dans vos fichiers, les remplace par des pseudonymes cohérents, et conserve une table de correspondance locale pour les retrouver après traitement.

## Fonctionnement

1. Vous déposez vos fichiers PDF, DOCX ou Markdown dans le dossier `input/`.
2. L'outil extrait le texte, détecte les données personnelles et les remplace par des pseudonymes : `[PERSONNE_001]`, `[EMAIL_001]`, `[ADRESSE_002]`…
3. Il écrit le texte pseudonymisé dans `output/`, avec une table de correspondance dans `output/mappings/`.

La pseudonymisation est cohérente sur tout le corpus : une même entité reçoit toujours le même pseudonyme, y compris sur plusieurs documents traités ensemble.


## Données détectées

| Catégorie | Exemples |
|---|---|
| `PERSONNE` | Jean DUPONT, Marie Martin |
| `EMAIL` | jean.martin@exemple.fr |
| `TEL` | 06 12 34 56 78 |
| `NIR` | numéro de sécurité sociale (clé de contrôle vérifiée) |
| `IBAN` | FR76 3000 6000 … (clé de contrôle vérifiée) |
| `SIREN`, `SIRET` | identifiants d'entreprise (clé de contrôle vérifiée) |
| `PLAQUE` | AB-123-CD |
| `DATE_NAISSANCE` | né le 15/03/1985 |
| `ADRESSE` | 12 rue de la Paix, 75001 Paris |
| `LIEU`, `COMMUNE` | domicilié à Lyon |
| `PERSONNE_MORALE` | SAS TechCorp, SARL Durand & Fils |
| `JURIDICTION` | Tribunal judiciaire de Paris |
| `NUM_DOSSIER` | RG n° 24/05123 |
| `AVOCAT`, `MAGISTRAT` | Maître Sophie DURAND, Président Martin (désactivés par défaut, voir ci-dessous) |

La détection combine des motifs d'expression régulière, des validateurs (Luhn, mod-97, clé du NIR), des règles propres au vocabulaire juridique français, et un modèle de reconnaissance d'entités nommées (spaCy, `fr_core_news_sm`).

## Installation

**Prérequis** : Python 3.10 ou supérieur.

```bash
git clone https://github.com/plocl67110/AInonymizer-PLONKA.git
cd AInonymizer-PLONKA
pip install -r requirements.txt
python -m spacy download fr_core_news_sm
```

Le téléchargement du modèle spaCy n'a lieu qu'une fois, à l'installation. Ensuite, le traitement fonctionne hors ligne.

Pour Windows, un guide de construction d'exécutable est fourni dans `BUILD_WINDOWS.md`.

## Utilisation

1. Placez vos fichiers PDF, DOCX ou MD dans le dossier `input/`.
2. Lancez l'outil :

```bash
python ainonymizer.py
```

3. Une fenêtre s'ouvre : choisissez les catégories à pseudonymiser, puis cliquez sur **Lancer**.
4. Récupérez les résultats dans `output/` :

```
output/
  DOC_001_anonymise.md          texte pseudonymisé, destiné au LLM
  mappings/
    DOC_001_mapping.json        table pseudonymes → valeurs d'origine
    corpus_mapping.json         table globale, avec la correspondance DOC_xxx → fichier source
```


## Limitations

- Les PDF scannés (images) ne sont pas traités : le texte doit être sélectionnable.
- La détection repose sur des règles et un modèle généraliste. Elle peut manquer des données inhabituelles et produire des faux positifs sur des termes ambigus.
- Une absence de détection ne prouve pas l'absence de données personnelles. Pour un usage avec un LLM, relisez les sorties, et ajoutez un contrôle résiduel.
- Optimisé pour le français.
- Les fichiers de `output/mappings/` contiennent les valeurs d'origine et la correspondance avec les fichiers sources. Ils restent locaux et ne doivent jamais être transmis à un LLM.

## Dépendances

- [PyMuPDF](https://pymupdf.readthedocs.io/) : lecture des PDF
- [python-docx](https://python-docx.readthedocs.io/) : lecture des DOCX
- [RapidFuzz](https://github.com/rapidfuzz/RapidFuzz) : distances entre chaînes (variantes orthographiques)
- [spaCy](https://spacy.io/) et le modèle `fr_core_news_sm` : reconnaissance d'entités nommées

Chaque dépendance reste soumise à sa propre licence. La liste complète figure dans `requirements.txt`.

## Crédits et attribution

AInonymizer a été conçu par **Florence Chatelot**, formatrice en outils d'IA, dans le dépôt d'origine [Miragide/AInonymizer](https://github.com/Miragide/AInonymizer).

Cette version est une modification de l'original, réalisée par **Claude PLONKA** :

- réécriture et extension de `regex_fr.py` (validateurs, déduplication par priorité, dates, adresses, communes) ;
- intégration de la détection par spaCy (`spacy_tools.py`) et de sa combinaison avec les détecteurs à base de règles (`anonymizer.py`) ;
- tests unitaires et documentation.

Florence Chatelot a autorisé la diffusion de cette version.

## Licence

Ce projet est distribué sous licence MIT. Voir [Licence.txt](Licence.txt).

## Soutenir le projet

Si cet outil vous fait gagner du temps, vous pouvez soutenir son évolution auprès de Florence Chatelot : [florence-chatelot.fr/stripe](https://florence-chatelot.fr/stripe).