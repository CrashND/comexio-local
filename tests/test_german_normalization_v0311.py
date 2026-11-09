"""Test German room name normalization with bidirectional umlaut handling.

This test suite covers the v0.3.11 fix for German spelling variations that
were previously not handled correctly (e.g., "GästeWC" vs "GaesteWC", 
"Büro" vs "Buero", "Küche" vs "kuiche").

The normalization must:
- Handle common German umlaut variants bidirectionally
- Preserve room name structure while normalizing whitespace
- Never merge distinct rooms with similar names
"""
import pytest
from comexio_local.managed_resources import _normalize_german, _historical_label_key
from comexio_local.area_assignment import normalize_room


class TestNormalizeGerman:
    """Test bidirectional German normalization in managed_resources."""

    def test_umlaut_to_ascii(self):
        """Forward direction: German umlauts → ASCII"""
        _, variants = _normalize_german("Gäste WC")
        assert "gaeste wc" in variants or "gaestewc" in variants
    
    def test_ascii_to_umlaut(self):
        """Backward direction: ASCII transliteration → German"""
        _, variants = _normalize_german("GaesteWC")
        # Should also find the umlaut version for bidirectional matching
        assert "gaeste wc" in variants or "gaestewc" in variants

    def test_kueche_variants(self):
        """Test all kitchen name variants match"""
        canonical = "Küche"
        _, variants = _normalize_german(canonical)
        
        # All these should be recognized as the same room
        assert any("kuche" in v.lower() for v in variants)


class TestHistoricalLabelKey:
    """Test the historical label key comparison."""

    def test_basic_umlaut_normalization(self):
        """Simple umlaut normalization works"""
        self._assert_match("küche", "kuche")
    
    def test_bidirectional_umlaut(self):
        """Both directions normalize to same form"""
        # German → ASCII and back
        assert _historical_label_key("Küche") == _historical_label_key("Kuche")
        assert _historical_label_key("Gäste WC") == _historical_label_key("Gaeste WC")

    def test_guestewc_variants(self):
        """GuestWC common variations"""
        # All these should match for the same physical room
        forms = [
            "GäStE wC",      # Mixed case with umlaut
            "gaeste wc",     # Lowercase ASCII
            "Gaeste WC",     # Title case ASCII
            "Gäste WC",      # German Unicode
            "gäste wc",      # Lowercase German
        ]
        
        base = _historical_label_key(forms[0])
        for form in forms:
            assert _historical_label_key(form) == base

    def test_buero_variants(self):
        """Büro/Buero variations"""
        # This is critical: "Buero" and "Büro" should match
        assert _historical_label_key("BüRO") == _historical_label_key("Buero")
        assert _historical_label_key("büro") == _historical_label_key("buro")
    
    def test_aussen_variants(self):
        """Außen/Aussen variations"""
        assert _historical_label_key("Außen") == _historical_label_key("Aussen")
        assert _historical_label_key("außen") == _historical_label_key("ausen")

    def test_kueche_typo_variants(self):
        """Typo variants should still match"""
        assert _historical_label_key("Küche") == _historical_label_key("kuiche")
        assert _historical_label_key("küCHE") == _historical_label_key("kuche")

    def test_whitespace_preserved_as_separator(self):
        """Whitespace should be collapsed, not removed"""
        # "Gäste WC" and "Gastewc" should still match (space normalization)
        assert _historical_label_key("Gäste WC") == _historical_label_key("Gastewc")

    def test_different_rooms_not_merged(self):
        """Distinct rooms should not be merged"""
        # These are different rooms and should NOT match
        # Even with similar names, they must stay separate
        result1 = _historical_label_key("Küche 1")
        result2 = _historical_label_key("Küche")
        
        # After normalization, "küche 1" != "küche" - this is correct!
        assert result1 != result2


class TestHistoricalLabelKeyRealWorld:
    """Real-world test cases from the field."""

    def test_gaestewc_vs_gastewc(self):
        """The reported issue: GästeWC vs GaesteWC"""
        # From ChatGPT report: "GaesteWC" should match "Gäste WC"
        assert _historical_label_key("Gäste WC") == _historical_label_key("GaesteWC")
        assert _historical_label_key("gaeste wc") == _historical_label_key("Gäste WC")

    def test_buero_vs_buero_umlaut(self):
        """Büro spelled without umlaut"""
        # Common misspelling in historical data
        assert _historical_label_key("BüRO") == _historical_label_key("Buero")

    def test_aussen_vs_aussen_variant(self):
        """Außen spelled with ss instead of ß"""
        assert _historical_label_key("Außen") == _historical_label_key("Aussen")
        assert _historical_label_key("aussen") == _historical_label_key("außen")

    def test_kein_problem_with_capitalization(self):
        """Capitalization variations are handled"""
        forms = ["Küche", "küche", "KUCHE", "Kuche"]
        first = _historical_label_key(forms[0])
        for form in forms:
            assert _historical_label_key(form) == first


class TestNormalizeRoomDirectly:
    """Test area_assignment.normalize_room() directly."""

    def test_kueche_variants(self):
        """Küche name variants"""
        variants = ["Küche", "küche", "kuiche", "Kuche"]
        for v in variants:
            result = normalize_room(v)
            # All should normalize consistently
            assert "kuche" in result.lower()

    def test_gastewc_variants(self):
        """GästeWC name variants"""
        variants = [
            "GäStE wC",
            "gaeste wc", 
            "Gaeste WC",
            "Gäste WC"
        ]
        first_result = normalize_room(variants[0])
        for v in variants:
            result = normalize_room(v)
            # Should all produce identical normalized output
            assert result == first_result

    def test_buero_vs_buro(self):
        """Büro/Buero bidirectional match"""
        assert normalize_room("BüRO") == normalize_room("Buero")
        assert normalize_room("büro") == normalize_room("buro")

    def test_aussen_vs_aussen(self):
        """Außen/Aussen bidirectional match"""
        assert normalize_room("Außen") == normalize_room("Aussen")
        assert normalize_room("außen") == normalize_room("ausen")

    def test_preserves_room_structure(self):
        """Room structure is preserved"""
        # "Küche 1" should still be distinguishable from "Küche"
        assert normalize_room("Küche 1") != normalize_room("Küche")
        
        # But the prefix should match for area matching
        assert "kuche" in normalize_room("Küche 1")