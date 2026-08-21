# Construire AInonymizer.exe sur Windows

Ce dossier contient le code source corrigé et validé (tests 65+9+6 passés).
La compilation en `.exe` doit se faire **sur Windows** — PyInstaller ne
fait pas de cross-compilation depuis un autre OS.

## 1. Prérequis

- Python 3.10+ installé sur la machine Windows (idéalement la même version
  que celle utilisée pour vos tests précédents : 3.10.11)
- Une invite de commande (PowerShell ou CMD) ouverte dans ce dossier

## 2. Installer les dépendances

```powershell
pip install -r requirements.txt
pip install pyinstaller
python -m spacy download fr_core_news_sm
```

## 3. Vérifier que tout fonctionne avant de compiler

```powershell
python test_ainonymizer.py
python -m pytest test_spacy_tools.py test_hardened.py -q
```

Les trois suites doivent passer intégralement (65 + 6 + 9 tests) avant de
lancer la compilation — un échec ici se reproduira à l'identique dans l'exe.

## 4. Compiler l'exécutable

Le fichier `data/communes2026.csv` (déjà inclus dans cette livraison) doit
rester à côté de `ainonymizer_corrige.spec` : le `.spec` l'embarque
explicitement dans l'exe.

```powershell
python -m PyInstaller --clean --noconfirm ainonymizer_corrige.spec
```

L'exécutable final est produit dans `dist\AInonymizer.exe`.

## 5. Test rapide de l'exe

```powershell
mkdir dist\input
copy un_fichier_test.pdf dist\input\
cd dist
.\AInonymizer.exe
```

Une fenêtre doit s'ouvrir listant les catégories à anonymiser. Après avoir
cliqué sur « Lancer », les fichiers `dist\output\*_anonymise.md` et
`dist\output\mappings\*_mapping.json` doivent apparaître.

## Remarques

- **Taille de l'exe** : attendez-vous à un exécutable volumineux (~150-200 Mo),
  spaCy embarque des dépendances scientifiques (scipy, matplotlib backends)
  même si seul le modèle NER français est réellement utilisé. Un premier
  lancement peut être plus lent (chargement du modèle spaCy).
- **Antivirus** : les exécutables PyInstaller onefile sont parfois signalés
  à tort par certains antivirus (faux positif classique lié au packaging,
  pas au code). Si besoin, une signature de code ou un exclusion locale
  résout le problème.
- Pour du texte issu de PDF scannés (images), l'extraction ne fonctionnera
  pas : `extractor.py` n'inclut pas d'OCR.
