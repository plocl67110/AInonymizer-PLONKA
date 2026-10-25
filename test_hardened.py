import unittest

from regex_fr import find_structured_pii, find_person_names, find_societes, find_avocats, find_magistrats, find_lieux
from juritools import reclassify_dates, resolve_overlaps, trim_particles
from pseudo_map import PseudoMap


class TestHardenedPII(unittest.TestCase):
    def cats(self, text):
        return [(m.category, m.text) for m in find_structured_pii(text)]

    def test_email(self):
        self.assertTrue(any(c == "EMAIL" for c, _ in self.cats("jean.dupont@example.fr")))

    def test_phone(self):
        self.assertTrue(any(c == "TEL" for c, _ in self.cats("06 12 34 56 78")))

    def test_invalid_date_not_detected(self):
        self.assertFalse(any(c == "DATE" for c, _ in self.cats("31/02/2020")))

    def test_nir_invalid_checksum_not_detected(self):
        self.assertFalse(any(c == "NIR" for c, _ in self.cats("1 85 05 75 123 456 78")))

    def test_person_context(self):
        matches = find_person_names("Monsieur Jean Dupont a comparu.")
        self.assertTrue(any(m.text == "Jean Dupont" for m in matches))

    def test_lawyer_is_person(self):
        matches = find_avocats("Maître Jean Dupont")
        self.assertTrue(any(m.category == "AVOCAT" for m in matches))
        self.assertFalse(any("Barreau de Paris" in m.text for m in matches))

    def test_place_is_bounded(self):
        matches = find_lieux("né à Strasbourg, le 12 mars 2020")
        self.assertTrue(any(m.text == "Strasbourg" for m in matches))

    def test_homonyms_can_be_distinct(self):
        pm = PseudoMap()
        a = pm.assign_identity("PERSONNE:E1", "Jean Dupont", "PERSONNE")
        b = pm.assign_identity("PERSONNE:E2", "Jean Dupont", "PERSONNE")
        self.assertNotEqual(a, b)

    def test_overlap_resolution(self):
        text = "né le 12/03/1980"
        ms = find_structured_pii(text)
        ms = reclassify_dates(text, ms)
        ms = resolve_overlaps(ms)
        self.assertTrue(any(m.category == "DATE_NAISSANCE" for m in ms))

    def test_madame_nom_pas_avocat(self):
        self.assertEqual(find_avocats("Madame Claire BERNARD expose que"), [])

    def test_maitre_nom_avocat(self):
        ms = find_avocats("Maître Sophie LEMAIRE, avocate")
        self.assertTrue(any(m.text == "Sophie LEMAIRE" for m in ms))

    def test_nom_de_famille_rattache_a_personne_unique(self):
        pm = PseudoMap()
        a = pm.assign("Julien MOREL", "PERSONNE")
        b = pm.assign("MOREL", "PERSONNE")
        self.assertEqual(a, b)

    def test_homonymes_non_fusionnes(self):
        pm = PseudoMap()
        a = pm.assign("Julien MOREL", "PERSONNE")
        c = pm.assign("Paul MOREL", "PERSONNE")
        d = pm.assign("MOREL", "PERSONNE")
        self.assertNotEqual(a, c)
        self.assertNotEqual(a, d)
        self.assertNotEqual(c, d)

    def test_prenom_seul_non_rattache(self):
        pm = PseudoMap()
        a = pm.assign("Julien MOREL", "PERSONNE")
        b = pm.assign("Julien", "PERSONNE")
        self.assertNotEqual(a, b)

    def test_avocat_prefixe_visible(self):
        pm = PseudoMap()
        p = pm.assign("Sophie LEMAIRE", "AVOCAT")
        self.assertTrue(p.startswith("AVOCAT_"))

    def test_iban_checksum_invalide_detecte(self):
        ms = find_structured_pii("IBAN FR76 3000 4000 0300 1234 5678 901")
        self.assertTrue(any(m.category == "IBAN" for m in ms))

    def test_iban_saut_de_ligne_detecte(self):
        ms = find_structured_pii("IBAN FR76 3000 4000 0300\n1234 5678 901")
        self.assertTrue(any(m.category == "IBAN" for m in ms))

    def test_libelles_administratifs_filtres(self):
        from regex_fr import is_label_noise
        self.assertTrue(is_label_noise("téléphone", "PERSONNE_MORALE"))
        self.assertTrue(is_label_noise("TÉLÉPHONE", "PERSONNE_MORALE"))
        self.assertTrue(is_label_noise("pour", "PERSONNE_MORALE"))
        self.assertTrue(is_label_noise("adresse", "LIEU"))
        self.assertTrue(is_label_noise("Dossier", "LIEU"))
        self.assertTrue(is_label_noise("MADAME", "PERSONNE"))

    def test_vrais_noms_conserves(self):
        from regex_fr import is_label_noise
        self.assertFalse(is_label_noise("Claire BERNARD", "PERSONNE"))
        self.assertFalse(is_label_noise("Strasbourg", "LIEU"))
        self.assertFalse(is_label_noise("Rhin-Moselle", "PERSONNE_MORALE"))

    def test_avocate_prenom_minuscule(self):
        ms = find_avocats("Me lucie GARNIER, avocate au Barreau")
        self.assertTrue(any(m.text == "lucie GARNIER" for m in ms))

    def test_societe_ne_commence_pas_par_chiffre(self):
        ms = find_societes("Dossier RG 2026/00317. Société SARL Boulangerie Dupuis")
        self.assertFalse(any(m.text.startswith("2026") for m in ms))

if __name__ == "__main__":
    unittest.main()
