"""
Tests unitaires pour le module spacy_tools.
"""
import pytest
from spacy_tools import find_spacy_entities, get_nlp

def test_spacy_model_loaded():
    """Test que le modèle spaCy est chargé correctement."""
    nlp = get_nlp()
    assert nlp is not None
    assert nlp.meta["name"] == "fr_core_news_sm"

def test_spacy_person_detection():
    """Test la détection des personnes avec spaCy."""
    text = "Jean Dupont est né à Paris en 1990."
    entities = find_spacy_entities(text)
    assert len(entities) >= 2  # Au moins "Jean Dupont" (PER) et "Paris" (LOC)
    assert any(e.category == "PERSONNE" and "Dupont" in e.text for e in entities)
    assert any(e.category == "LIEU" and "Paris" in e.text for e in entities)

def test_spacy_org_detection():
    """Test la détection des organisations avec spaCy."""
    text = "La société Martin & Cie a son siège à Lyon."
    entities = find_spacy_entities(text)
    assert any(e.category == "PERSONNE_MORALE" and "Martin & Cie" in e.text for e in entities)
    assert any(e.category == "LIEU" and "Lyon" in e.text for e in entities)

def test_spacy_date_detection():
    """Test la détection des dates avec spaCy."""
    text = "Le contrat a été signé le 15 août 2023."
    entities = find_spacy_entities(text)
    assert any(e.category == "DATE" for e in entities)

def test_spacy_no_entities():
    """Test qu'aucun résultat n'est retourné pour un texte sans entités."""
    text = "Ceci est un texte sans entités nommées."
    entities = find_spacy_entities(text)
    assert len(entities) == 0

def test_spacy_entity_attributes():
    """Test que les attributs des entités sont corrects."""
    text = "Marie Martin travaille chez Google."
    entities = find_spacy_entities(text)
    for e in entities:
        assert hasattr(e, "start")
        assert hasattr(e, "end")
        assert hasattr(e, "text")
        assert hasattr(e, "category")
        assert hasattr(e, "confidence")
        assert hasattr(e, "source")
        assert e.source == "spacy"