#!/usr/bin/env python3
"""
Tests de régression pour AInonymizer.
Exécuter : python test_ainonymizer.py
Aucune dépendance externe requise (ne teste pas l'extraction PDF/DOCX).
"""
import sys
import traceback

# Force UTF-8 sur Windows (console CP1252 par défaut)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ─── Résultat de test ─────────────────────────────────────────────────

PASS = 0
FAIL = 0


def ok(label: str, detail: str = "") -> None:
    global PASS
    PASS += 1
    print(f"  OK  {label}")


def fail(label: str, detail: str = "") -> None:
    global FAIL
    FAIL += 1
    msg = f"  FAIL  {label}"
    if detail:
        msg += f"\n        detail: {detail}"
    print(msg)


def expect(label: str, condition: bool, detail: str = "") -> None:
    (ok if condition else fail)(label, detail)


# ═══════════════════════════════════════════════════════════════════════
#  1. Checksums
# ═══════════════════════════════════════════════════════════════════════

def test_checksums() -> None:
    print("\n── Checksums ─────────────────────────────────────────────")
    from regex_fr import _validate_iban, _validate_nir, _validate_siren

    # IBAN valides
    expect("IBAN FR valide", _validate_iban("FR7630006000011234567890189"))
    expect("IBAN FR avec espaces", _validate_iban("FR76 3000 6000 0112 3456 7890 189"))
    expect("IBAN DE valide", _validate_iban("DE89370400440532013000"))
    # IBAN invalides
    expect("IBAN invalide (mod-97 ≠ 1)", not _validate_iban("FR7630006000011234567890188"))
    expect("IBAN trop court", not _validate_iban("FR76300"))

    # SIREN valides (Luhn)
    expect("SIREN valide 552 032 534", _validate_siren("552032534"))
    expect("SIREN avec espaces", _validate_siren("552 032 534"))
    # SIREN invalides
    expect("SIREN invalide (Luhn KO)", not _validate_siren("123456789"))
    expect("SIREN commençant par 0", not _validate_siren("012345678"))
    expect("SIREN tous identiques", not _validate_siren("111111111"))

    # NIR valides — clé = 97 - (1850575123456 % 97) = 97 - 24 = 73
    expect("NIR valide 1 85 05 75 123 456 73",
           _validate_nir("1 85 05 75 123 456 73"))
    # NIR invalide
    expect("NIR invalide (clé 78 au lieu de 73)", not _validate_nir("1 85 05 75 123 456 78"))
    expect("NIR trop court", not _validate_nir("185057512345"))


# ═══════════════════════════════════════════════════════════════════════
#  2. Détection PII structurée
# ═══════════════════════════════════════════════════════════════════════

def test_structured_pii() -> None:
    print("\n── PII structurée ────────────────────────────────────────")
    from regex_fr import find_structured_pii, find_adresses
    from juritools import reclassify_dates

    text = (
        "Contacter jean.martin@exemple.fr ou 06 12 34 56 78.\n"
        "IBAN FR76 3000 6000 0112 3456 7890 189.\n"
        "SIREN 552 032 534.\n"
        "NIR : 1 85 05 75 123 456 73.\n"
        "RG n°24/12345.\n"
        "Né le 15/03/1985 à Paris.\n"
        "Audience du 12/06/2024.\n"
        "Domicile : 12 rue de la Paix, 75001 Paris.\n"
    )

    matches = find_structured_pii(text)
    matches = reclassify_dates(text, matches)
    matches.extend(find_adresses(text))
    cats = {m.category for m in matches}

    expect("EMAIL détecté", "EMAIL" in cats, str(cats))
    expect("TEL détecté", "TEL" in cats, str(cats))
    expect("IBAN détecté", "IBAN" in cats, str(cats))
    expect("SIREN détecté", "SIREN" in cats, str(cats))
    expect("NIR détecté", "NIR" in cats, str(cats))
    expect("NUM_DOSSIER détecté", "NUM_DOSSIER" in cats, str(cats))
    expect("DATE_NAISSANCE détecté (né le)", "DATE_NAISSANCE" in cats, str(cats))
    expect("ADRESSE détectée", "ADRESSE" in cats, str(cats))

    ibans = [m for m in matches if m.category == "IBAN"]
    expect("IBAN texte correct", any("FR76" in m.text for m in ibans),
           str([m.text for m in ibans]))


# ═══════════════════════════════════════════════════════════════════════
#  3. Détection de personnes
# ═══════════════════════════════════════════════════════════════════════

def test_person_names() -> None:
    print("\n── Noms de personnes ─────────────────────────────────────")
    from regex_fr import find_person_names, find_avocats

    text = (
        "Monsieur Jean DUPONT a assigné Madame Marie MARTIN.\n"
        "Le demandeur Pierre LEBLANC est représenté par Maître Sophie DURAND.\n"
        "ENTRE : François BERNARD et la société SAS TechCorp.\n"
    )

    persons = find_person_names(text)
    person_texts = [m.text for m in persons]

    expect("Jean DUPONT détecté", any("DUPONT" in t for t in person_texts),
           str(person_texts))
    expect("Marie MARTIN détectée", any("MARTIN" in t for t in person_texts),
           str(person_texts))
    expect("Pierre LEBLANC détecté", any("LEBLANC" in t for t in person_texts),
           str(person_texts))
    expect("François BERNARD détecté (ENTRE pattern)", any("BERNARD" in t for t in person_texts),
           str(person_texts))

    avocats = find_avocats(text)
    avocat_texts = [m.text for m in avocats]
    expect("Sophie DURAND détectée comme AVOCAT", any("DURAND" in t for t in avocat_texts),
           str(avocat_texts))

    # Pattern NOM (majuscules) Prénom (titre)
    text2 = (
        "PERROT Claudine a déclaré. "
        "MARTIN-DUPONT Marie-France était présente. "
        "CHAMBRE Civile — ARTICLE Premier."
    )
    persons2 = find_person_names(text2)
    texts2 = [m.text for m in persons2]
    expect("PERROT Claudine détecté",
           any("PERROT" in t for t in texts2), str(texts2))
    expect("MARTIN-DUPONT Marie-France détecté",
           any("MARTIN-DUPONT" in t for t in texts2), str(texts2))
    expect("CHAMBRE Civile non détecté (stopword)",
           not any(m.text == "CHAMBRE Civile" for m in persons2), str(texts2))
    expect("ARTICLE Premier non détecté (stopword)",
           not any(m.text == "ARTICLE Premier" for m in persons2), str(texts2))


# ═══════════════════════════════════════════════════════════════════════
#  4. PseudoMap — cohérence cross-document
# ═══════════════════════════════════════════════════════════════════════

def test_pseudo_map() -> None:
    print("\n── PseudoMap ─────────────────────────────────────────────")
    from pseudo_map import PseudoMap

    pm = PseudoMap()

    p1 = pm.assign("Jean DUPONT", "PERSONNE")
    p2 = pm.assign("jean dupont", "PERSONNE")   # normalisé → même pseudonyme
    p3 = pm.assign("Marie MARTIN", "PERSONNE")
    p4 = pm.assign("Jean DUPONT", "PERSONNE")   # déjà connu

    expect("Pseudonyme format PERSONNE_001", p1 == "PERSONNE_001", p1)
    expect("Casse ignorée pour cohérence", p1 == p2, f"{p1} ≠ {p2}")
    expect("Entité différente → pseudonyme différent", p1 != p3, f"{p1} == {p3}")
    expect("Même entité → même pseudonyme", p1 == p4, f"{p1} ≠ {p4}")

    d = pm.to_dict()
    expect("to_dict contient PERSONNE_001", "PERSONNE_001" in d, str(d))
    expect("Valeur originale préservée", d["PERSONNE_001"] == "Jean DUPONT",
           d.get("PERSONNE_001"))


# ═══════════════════════════════════════════════════════════════════════
#  5. Pipeline complet — apply_pseudonyms
# ═══════════════════════════════════════════════════════════════════════

def test_pipeline() -> None:
    print("\n── Pipeline complet ──────────────────────────────────────")
    from anonymizer import analyze, apply_pseudonyms
    from pseudo_map import PseudoMap

    text = (
        "Monsieur Jean DUPONT, né le 15/03/1985, demeurant au "
        "12 rue de la Paix 75001 Paris, titulaire du compte "
        "FR76 3000 6000 0112 3456 7890 189, a contacté "
        "jean.dupont@example.com pour l'audience du 10/01/2024.\n"
        "Jean DUPONT a ensuite rencontré Madame Marie MARTIN.\n"
    )

    pm = PseudoMap()
    entities = analyze(text, pm)
    anonymized = apply_pseudonyms(text, entities)

    expect("Nom DUPONT remplacé", "DUPONT" not in anonymized, anonymized[:200])
    expect("IBAN remplacé", "FR76 3000" not in anonymized, anonymized[:200])
    expect("Email remplacé", "jean.dupont@example.com" not in anonymized, anonymized[:200])
    expect("Date de naissance remplacée", "15/03/1985" not in anonymized, anonymized[:200])
    expect("Date procédurale conservée", "10/01/2024" in anonymized, anonymized[:300])

    enabled = [e for e in entities if e.enabled and "DUPONT" in e.text]
    pseudos = {e.pseudonym for e in enabled}
    expect("Cohérence cross-occurrence DUPONT", len(pseudos) == 1,
           f"pseudonymes distincts : {pseudos}")

    import re
    placeholders = re.findall(r"\[([A-Z_]+_\d{3})\]", anonymized)
    expect("Pseudonymes au format [CAT_NNN] présents", len(placeholders) > 0,
           anonymized[:300])


# ═══════════════════════════════════════════════════════════════════════
#  6. Post-traitement — reclassification dates & propagation
# ═══════════════════════════════════════════════════════════════════════

def test_postprocess() -> None:
    print("\n── Post-traitement ───────────────────────────────────────")
    from regex_fr import find_structured_pii
    from juritools import propagate_multi_occurrences, reclassify_dates

    text = "née le 12/05/1990, arrêt du 03/06/2023."
    raw = find_structured_pii(text)
    reclassified = reclassify_dates(text, raw)
    cats_after = {m.category for m in reclassified}

    expect("DATE_NAISSANCE conservée après reclassification",
           "DATE_NAISSANCE" in cats_after, str(cats_after))
    expect("Date procédurale supprimée (arrêt du)",
           not any(m.text == "03/06/2023" for m in reclassified),
           str([(m.category, m.text) for m in reclassified]))

    from regex_fr import RawMatch
    text2 = "Jean DUPONT a signé. Jean DUPONT était présent."
    seed = [RawMatch(start=0, end=11, text="Jean DUPONT", category="PERSONNE")]
    propagated = propagate_multi_occurrences(text2, seed)
    positions = [m.start for m in propagated]
    expect("Propagation détecte la 2ème occurrence", len(propagated) >= 1,
           f"positions trouvées : {positions}")


# ═══════════════════════════════════════════════════════════════════════
#  7. Corrections de l'audit RGPD/LLM (2026)
# ═══════════════════════════════════════════════════════════════════════

def test_corrections() -> None:
    print("\n── Corrections audit ─────────────────────────────────────")

    # 7.1 — NIR corse (2A/2B) : jamais détecté avant correction, faute de
    #       cohérence entre le pattern (chiffres uniquement) et la clé de
    #       contrôle (qui gérait déjà 2A/2B → 19/18).
    from regex_fr import _validate_nir, find_structured_pii

    num = "185032A034123"
    key = 97 - int(num.replace("2A", "19")) % 97
    nir_corse = f"{num}{key:02d}"
    expect("Checksum NIR corse valide (contrôle du test lui-même)",
           _validate_nir(nir_corse), nir_corse)

    formatted = f"{nir_corse[0]} {nir_corse[1:3]} {nir_corse[3:5]} {nir_corse[5:7]} {nir_corse[7:10]} {nir_corse[10:13]} {nir_corse[13:]}"
    matches = find_structured_pii(f"NIR : {formatted}.")
    expect("NIR corse (2A) détecté", any(m.category == "NIR" for m in matches),
           str([(m.category, m.text) for m in matches]))

    num_b = "285032B034123"
    key_b = 97 - int(num_b.replace("2B", "18")) % 97
    nir_corse_b = f"{num_b}{key_b:02d}"
    formatted_b = f"{nir_corse_b[0]} {nir_corse_b[1:3]} {nir_corse_b[3:5]} {nir_corse_b[5:7]} {nir_corse_b[7:10]} {nir_corse_b[10:13]} {nir_corse_b[13:]}"
    matches_b = find_structured_pii(f"NIR : {formatted_b}.")
    expect("NIR corse (2B) détecté", any(m.category == "NIR" for m in matches_b),
           str([(m.category, m.text) for m in matches_b]))

    # Non-régression : un NIR standard (département métropolitain) doit
    # toujours être détecté après le repositionnement du groupe département.
    num_std = "1850175116012"
    key_std = 97 - int(num_std) % 97
    nir_std = f"{num_std}{key_std:02d}"
    matches_std = find_structured_pii(f"NIR : {nir_std}.")
    expect("NIR standard toujours détecté (non-régression)",
           any(m.category == "NIR" for m in matches_std),
           str([(m.category, m.text) for m in matches_std]))

    # 7.2 — Cohérence pseudonyme/catégorie : une même personne détectée une
    #       fois comme AVOCAT ("Maître X") et une fois comme PERSONNE ("M. X")
    #       ne doit plus produire une redaction partielle et incohérente.
    from anonymizer import analyze, apply_pseudonyms
    from pseudo_map import PseudoMap

    text_avocat = "Maître Dupont a plaidé. M. Dupont a ensuite quitté la salle."
    pm = PseudoMap()
    entities = analyze(text_avocat, pm)
    dupont_entities = [e for e in entities if "Dupont" in e.text]
    statuses = {e.enabled for e in dupont_entities}
    pseudos = {e.pseudonym for e in dupont_entities}
    expect("Statut enabled cohérent sur toutes les occurrences de Dupont",
           len(statuses) == 1, f"statuts trouvés : {statuses}")
    expect("Pseudonyme identique sur toutes les occurrences de Dupont",
           len(pseudos) == 1, f"pseudonymes trouvés : {pseudos}")
    result_avocat = apply_pseudonyms(text_avocat, entities)
    expect("Aucune occurrence de Dupont ne fuite dans un état intermédiaire",
           result_avocat.count("Dupont") in (0, 2), repr(result_avocat))

    # 7.3 — Avocat désactivé par défaut (délibération CNIL 01-057), mais
    #       activable explicitement — c'est ce que fait la case à cocher
    #       "Avocats" de la GUI (décochée par défaut, gui.py:_CATEGORIES).
    pm2 = PseudoMap()
    entities_default = analyze(text_avocat, pm2)
    avocat_default = [e for e in entities_default if e.category == "AVOCAT"]
    expect("Avocat désactivé par défaut",
           avocat_default and all(not e.enabled for e in avocat_default),
           str([(e.category, e.enabled) for e in entities_default]))

    pm3 = PseudoMap()
    entities_enabled = analyze(
        text_avocat,
        pm3,
        disabled_categories=frozenset({"MAGISTRAT"}),
    )
    avocat_enabled = [e for e in entities_enabled if e.category == "AVOCAT"]
    expect("Avocat activable via disabled_categories (choix utilisateur respecté)",
           avocat_enabled and all(e.enabled for e in avocat_enabled),
           str([(e.category, e.enabled) for e in entities_enabled]))

        # 7.4 — Propagation sans frontière de mot : un nom court ne doit plus se
    #       propager à l'intérieur d'un mot plus long qui le contient.
    from juritools import propagate_multi_occurrences
    from regex_fr import RawMatch

    text_frontiere = (
        "Marie a parlé. "
        "Mariette Dupont écoutait. "
        "Marie est repartie."
    )

    seed = [
        RawMatch(
            start=0,
            end=5,
            text="Marie",
            category="PERSONNE",
        )
    ]

    added = propagate_multi_occurrences(text_frontiere, seed)

    found_texts = [
        text_frontiere[a.start:a.end]
        for a in added
    ]

    found_positions = [
        a.start
        for a in added
    ]

    expect(
        "Marie propagé uniquement comme mot entier",
        found_texts == ["Marie"],
        str(found_texts),
    )

    expect(
        "Mariette non contaminé par Marie",
        "Mariette" not in found_texts,
        str(found_texts),
    )

    expect(
        "Une seule nouvelle occurrence de Marie",
        len(added) == 1,
        str([
            (a.start, a.end, text_frontiere[a.start:a.end])
            for a in added
        ]),
    )

    expect(
        "Occurrence propagée = dernière occurrence de Marie",
        found_positions == [text_frontiere.rfind("Marie")],
        str(found_positions),
    )

    # 7.5 — Date de naissance non supprimée à tort par un contexte
    #       procédural ambigu à proximité.
    from juritools import reclassify_dates
    from regex_fr import find_structured_pii as _fsp

    text_date = "M. Martin, né le 12/05/1990, a comparu à l'audience du 03/06/2023."
    raw_dates = [m for m in _fsp(text_date) if m.category in ("DATE", "DATE_NAISSANCE")]
    # On force la catégorie DATE générique pour tester reclassify_dates isolément
    from regex_fr import RawMatch as _RM
    generic = [
        _RM(text_date.index("12/05/1990"), text_date.index("12/05/1990") + 10, "12/05/1990", "DATE"),
        _RM(text_date.index("03/06/2023"), text_date.index("03/06/2023") + 10, "03/06/2023", "DATE"),
    ]
    reclassified = reclassify_dates(text_date, generic)
    expect("Date de naissance reclassée et conservée",
           any(m.category == "DATE_NAISSANCE" and m.text == "12/05/1990" for m in reclassified),
           str([(m.category, m.text) for m in reclassified]))
    expect("Date procédurale toujours filtrée",
           not any(m.text == "03/06/2023" for m in reclassified),
           str([(m.category, m.text) for m in reclassified]))

    # 7.6 — Nom court de 2 lettres (ex. patronyme d'origine asiatique) : ne
    #       doit plus être systématiquement écarté.
    from juritools import flag_doubtful_entities

    court = [RawMatch(start=0, end=2, text="Li", category="PERSONNE")]
    kept = flag_doubtful_entities(court)
    expect("Nom de 2 lettres conservé", len(kept) == 1, str(kept))

    initiale = [RawMatch(start=0, end=1, text="X", category="PERSONNE")]
    dropped = flag_doubtful_entities(initiale)
    expect("Initiale isolée toujours écartée", len(dropped) == 0, str(dropped))

    # 7.7 — Normalisation PseudoMap : tiret vs espace doivent fusionner.
    pm4 = PseudoMap()
    pa = pm4.assign("Jean-Dupont", "PERSONNE")
    pb = pm4.assign("Jean Dupont", "PERSONNE")
    expect("Tiret et espace fusionnent vers le même pseudonyme", pa == pb, f"{pa} ≠ {pb}")


# ═══════════════════════════════════════════════════════════════════════
#  8. Sortie Markdown
# ═══════════════════════════════════════════════════════════════════════

def test_markdown_output() -> None:
    print("\n── Format Markdown ───────────────────────────────────────")
    from anonymizer import analyze, apply_pseudonyms
    from pseudo_map import PseudoMap
    import re

    text = "Monsieur Paul DUMONT, SIREN 552 032 534, tél. 06 99 88 77 66."
    pm = PseudoMap()
    entities = analyze(text, pm)
    anon = apply_pseudonyms(text, entities)

    pattern = re.compile(r"\[[A-Z_]+_\d{3}\]")
    found = pattern.findall(anon)
    expect("Pseudonymes entre crochets dans la sortie", len(found) > 0, repr(anon))
    expect("DUMONT absent de la sortie", "DUMONT" not in anon, repr(anon))

    print(f"  → Exemple de sortie : {repr(anon[:120])}")

# ═══════════════════════════════════════════════════════════════════════
#  9. Communes INSEE — intégration pipeline
# ═══════════════════════════════════════════════════════════════════════

def test_communes_integration() -> None:
    print("\n── Communes INSEE — intégration ──────────────────────────")

    import communes_fr
    from anonymizer import analyze, apply_pseudonyms
    from pseudo_map import PseudoMap

    expect(
        "COG communes chargé",
        communes_fr.communes_count() > 30000,
        str(communes_fr.communes_count()),
    )

    text = (
        "Jean DUPONT est né à Strasbourg. "
        "Il réside à Haguenau. "
        "Le tribunal de Colmar traite le dossier. "
        "La procédure concerne Châlons-en-Champagne."
    )

    matches = communes_fr.find_communes(text)

    names = {m.text for m in matches}

    expect(
        "Strasbourg détecté",
        "Strasbourg" in names,
        str(names),
    )

    expect(
        "Haguenau détecté",
        "Haguenau" in names,
        str(names),
    )

    expect(
        "Colmar détecté",
        "Colmar" in names,
        str(names),
    )

    expect(
        "Châlons-en-Champagne détecté",
        "Châlons-en-Champagne" in names,
        str(names),
    )

    # Vérification de l'intégration complète.
    pm = PseudoMap()
    entities = analyze(text, pm, frozenset())

    lieux = [
        e for e in entities
        if e.category == "LIEU"
    ]

    lieu_texts = {e.text for e in lieux}

    expect(
        "Les communes remontent dans analyze()",
        {"Strasbourg", "Haguenau", "Colmar", "Châlons-en-Champagne"}
        <= lieu_texts,
        str(lieu_texts),
    )

    anonymized = apply_pseudonyms(text, entities)

    expect(
        "Strasbourg pseudonymisé",
        "Strasbourg" not in anonymized,
        repr(anonymized),
    )

    expect(
        "Haguenau pseudonymisé",
        "Haguenau" not in anonymized,
        repr(anonymized),
    )

    expect(
        "Colmar pseudonymisé",
        "Colmar" not in anonymized,
        repr(anonymized),
    )

    expect(
        "Châlons-en-Champagne pseudonymisé",
        "Châlons-en-Champagne" not in anonymized,
        repr(anonymized),
    )

    print(f"  → Lieux détectés : {sorted(lieu_texts)}")



# ═══════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════

def main() -> None:
    print("AInonymizer -- tests de régression\n" + "=" * 50)

    suites = [
        test_checksums,
        test_structured_pii,
        test_person_names,
        test_pseudo_map,
        test_pipeline,
        test_postprocess,
        test_corrections,
        test_markdown_output,
        test_communes_integration,
        test_no_confidential_entity_leak_in_output,
        test_no_sensitive_pattern_leak_in_output,
        test_active_entities_are_replaced_positionally,
    ]

    for suite in suites:
        try:
            suite()
        except Exception:
            global FAIL
            FAIL += 1
            print(f"\n  ✗  EXCEPTION dans {suite.__name__}:")
            traceback.print_exc()

    print(f"\n{'=' * 50}")
    print(f"  {PASS} passe(s)   {FAIL} echoue(s)")

    if FAIL:
        print("\n  Des corrections sont nécessaires avant utilisation.")
        sys.exit(1)
    else:
        print("\n  Tous les tests passent — moteur opérationnel.")
        sys.exit(0)

def test_no_confidential_entity_leak_in_output() -> None:
    from anonymizer import analyze, apply_pseudonyms
    from pseudo_map import PseudoMap

    text = (
        "Monsieur Jean DUPONT, né le 15/03/1985, "
        "demeurant au 12 rue de la Paix 75001 Paris. "
        "Jean DUPONT a contacté jean.dupont@example.com. "
        "Le dossier concerne la société ACME SAS."
    )

    pm = PseudoMap()
    entities = analyze(text, pm)
    anonymized = apply_pseudonyms(text, entities)

    confidential = [
        e for e in entities
        if e.enabled and e.text.strip()
    ]

    leaks = []

    for e in confidential:
        original = e.text.strip()

        if original in anonymized:
            leaks.append(
                {
                    "category": e.category,
                    "original": original,
                    "start": e.start,
                    "end": e.end,
                    "pseudonym": e.pseudonym,
                }
            )

    expect(
        "Aucune entité confidentielle ne reste dans la sortie",
        not leaks,
        repr(leaks),
    )

def test_no_sensitive_pattern_leak_in_output() -> None:
    import re

    from anonymizer import analyze, apply_pseudonyms
    from pseudo_map import PseudoMap

    text = (
        "Jean DUPONT, "
        "email jean.dupont@example.com, "
        "t?l?phone 06 12 34 56 78, "
        "SIRET 12345678901234, "
        "IBAN FR76 3000 6000 0112 3456 7890 189."
    )

    pm = PseudoMap()
    entities = analyze(text, pm)
    anonymized = apply_pseudonyms(text, entities)

    patterns = {
        "EMAIL": re.compile(
            r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
            re.IGNORECASE,
        ),
        "TEL": re.compile(
            r"(?<!\d)(?:0[1-9](?:[\s.-]?\d{2}){4})(?!\d)"
        ),
        "SIRET": re.compile(
            r"(?<!\d)\d{14}(?!\d)"
        ),
        "IBAN": re.compile(
            r"\b[A-Z]{2}\d{2}(?:[\s]?[A-Z0-9]){11,30}\b",
            re.IGNORECASE,
        ),
    }

    leaks = {}

    for category, pattern in patterns.items():
        matches = pattern.findall(anonymized)

        if matches:
            leaks[category] = matches

    expect(
        "Aucun motif sensible ne fuit dans la sortie",
        not leaks,
        repr(leaks),
    )

def test_active_entities_are_replaced_positionally() -> None:
    from anonymizer import analyze, apply_pseudonyms
    from pseudo_map import PseudoMap

    text = (
        "Jean DUPONT habite à Strasbourg. "
        "Jean DUPONT est né le 15/03/1985. "
        "Strasbourg reste mentionnée ailleurs."
    )

    pm = PseudoMap()
    entities = analyze(text, pm)
    anonymized = apply_pseudonyms(text, entities)

    active = [
        e for e in entities
        if e.enabled and e.pseudonym
    ]

    # Reconstruction indépendante de la sortie attendue.
    #
    # IMPORTANT :
    # e.pseudonym ne contient PAS les crochets — c'est apply_pseudonyms()
    # qui les ajoute au moment du remplacement (parts.append(f"[{e.pseudonym}]")
    # dans anonymizer.py). Il faut donc les ajouter ici aussi pour comparer
    # des sorties équivalentes.
    parts = []
    cursor = 0

    for e in sorted(active, key=lambda x: (x.start, x.end)):
        parts.append(text[cursor:e.start])
        parts.append(f"[{e.pseudonym}]")
        cursor = e.end

    parts.append(text[cursor:])

    expected = "".join(parts)

    expect(
        "Chaque entité active est remplacée à sa position",
        anonymized == expected,
        "La sortie réelle diffère de la reconstruction positionnelle.",
    )
def test_apply_pseudonyms_real_positional_mapping_197_entities():
    from pathlib import Path

    from extractor import extract
    from anonymizer import analyze, apply_pseudonyms, PseudoMap

    path = Path(r"C:\Dev\ainonymizer\input\CONC ME DUDKIEWICZ_ocred.pdf")

    text = extract(path)
    pm = PseudoMap()
    entities = analyze(text, pm)

    active = sorted(
        (
            e for e in entities
            if e.enabled and e.pseudonym
        ),
        key=lambda e: (e.start, e.end),
    )

    anonymized = apply_pseudonyms(text, entities)

    # Le corpus de référence doit contenir exactement 197 occurrences.
    assert len(active) == 197

    # Reconstruction indépendante de la sortie réelle.
    #
    # IMPORTANT :
    # apply_pseudonyms() encapsule le pseudonyme sous la forme
    # [PSEUDONYME].
    parts = []
    cursor = 0

    for entity in active:
        assert 0 <= entity.start < entity.end <= len(text)

        original = text[entity.start:entity.end]
        assert original

        replacement = f"[{entity.pseudonym}]"

        parts.append(text[cursor:entity.start])
        parts.append(replacement)

        cursor = entity.end

    parts.append(text[cursor:])

    expected = "".join(parts)

    # Vérification globale.
    assert anonymized == expected

    # Vérification positionnelle occurrence par occurrence.
    cumulative_delta = 0

    for index, entity in enumerate(active, start=1):
        original_len = entity.end - entity.start
        replacement = f"[{entity.pseudonym}]"

        transformed_start = entity.start + cumulative_delta
        transformed_end = transformed_start + len(replacement)

        actual = anonymized[transformed_start:transformed_end]

        assert actual == replacement, (
            f"Entité #{index} mal transformée : "
            f"span=({entity.start}, {entity.end}), "
            f"original={text[entity.start:entity.end]!r}, "
            f"expected={replacement!r}, "
            f"actual={actual!r}, "
            f"transformed_span=({transformed_start}, {transformed_end})"
        )

        cumulative_delta += len(replacement) - original_len


if __name__ == "__main__":
    main()

