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


if __name__ == "__main__":
    unittest.main()
