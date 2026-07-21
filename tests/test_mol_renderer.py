"""Tests for the SVG molecule renderer (pure RDKit, no Qt needed)."""

from __future__ import annotations

from rdkit import Chem

from wawekit.services.rendering.mol_renderer import render_svg


def _mol(smiles: str) -> Chem.Mol:
    mol = Chem.MolFromSmiles(smiles)
    assert mol is not None
    return mol


def test_render_returns_svg_document():
    svg = render_svg(_mol("CCO"))
    assert "<svg" in svg
    assert "</svg>" in svg


def test_render_generates_coords_for_smiles_mol():
    # A molecule fresh from SMILES has no conformers; rendering must still work.
    mol = _mol("c1ccccc1")
    assert mol.GetNumConformers() == 0
    svg = render_svg(mol)
    assert "<svg" in svg


def test_render_does_not_mutate_input():
    mol = _mol("CCO")
    render_svg(mol)
    # The copy inside render_svg received coordinates; the original must not.
    assert mol.GetNumConformers() == 0


def test_dark_and_light_render_differently():
    mol = _mol("c1ccncc1")
    assert render_svg(mol, dark=True) != render_svg(mol, dark=False)


def test_legend_is_included():
    # RDKit draws legend text as vector glyph paths (not <text>), so we check
    # for the legend elements rather than the literal string.
    with_legend = render_svg(_mol("CCO"), legend="ethanol")
    without_legend = render_svg(_mol("CCO"))
    assert "legend" in with_legend
    assert "legend" not in without_legend


def test_custom_size_respected():
    svg = render_svg(_mol("CCO"), width=222, height=111)
    assert "222" in svg and "111" in svg


def test_highlight_atoms_changes_the_drawing():
    mol = _mol("c1ccncc1")
    plain = render_svg(mol)
    highlighted = render_svg(mol, highlight_atoms=[0, 1, 2])
    # Highlighting adds elements (the highlight ellipses/regions), so the SVG grows.
    assert highlighted != plain
    assert len(highlighted) > len(plain)


def test_highlight_does_not_mutate_input():
    mol = _mol("c1ccccc1")
    render_svg(mol, highlight_atoms=[0, 1, 2])
    assert mol.GetNumConformers() == 0  # still the untouched input


def test_render_png_returns_png_bytes():
    from wawekit.services.rendering.mol_renderer import render_png

    png = render_png(_mol("CCO"))
    assert isinstance(png, bytes)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic number


def test_render_png_does_not_mutate_input():
    from wawekit.services.rendering.mol_renderer import render_png

    mol = _mol("c1ccccc1")
    render_png(mol)
    assert mol.GetNumConformers() == 0
