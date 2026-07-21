"""Tests for the PropertyRangeFilter and its proxy integration."""

from __future__ import annotations

from rdkit import Chem

from wawekit.gui.widgets.molecule_filter import PropertyRangeFilter
from wawekit.models.descriptors import DescriptorSet
from wawekit.models.molecule import MoleculeRecord


def test_property_range_filter_matches():
    """Verify that PropertyRangeFilter filters records based on bounds."""
    # Record A: MW = 100.0, LogP = 1.0
    rec_a = MoleculeRecord(mol=Chem.MolFromSmiles("CC"), name="A")
    rec_a.descriptors = DescriptorSet(
        molecular_weight=100.0,
        logp=1.0,
        tpsa=10.0,
        h_bond_donors=0,
        h_bond_acceptors=0,
        rotatable_bonds=0,
        ring_count=0,
    )

    # Record B: MW = 300.0, LogP = 3.0
    rec_b = MoleculeRecord(mol=Chem.MolFromSmiles("CCCC"), name="B")
    rec_b.descriptors = DescriptorSet(
        molecular_weight=300.0,
        logp=3.0,
        tpsa=20.0,
        h_bond_donors=0,
        h_bond_acceptors=0,
        rotatable_bonds=1,
        ring_count=0,
    )

    # Record C: No descriptors
    rec_c = MoleculeRecord(mol=Chem.MolFromSmiles("O"), name="C")

    # Filter 1: MW between 50 and 150
    filt1 = PropertyRangeFilter(ranges={"mw": (50.0, 150.0)})
    assert filt1.matches(rec_a) is True
    assert filt1.matches(rec_b) is False
    assert filt1.matches(rec_c) is False  # uncomputed is hidden

    # Filter 2: MW 50-350 AND LogP 2-4
    filt2 = PropertyRangeFilter(ranges={"mw": (50.0, 350.0), "logp": (2.0, 4.0)})
    assert filt2.matches(rec_a) is False  # LogP too low
    assert filt2.matches(rec_b) is True
