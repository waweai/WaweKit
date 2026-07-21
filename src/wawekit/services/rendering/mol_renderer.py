"""2D molecule depiction as SVG.

RDKit's modern drawing engine (:mod:`rdkit.Chem.Draw.rdMolDraw2D`) renders a
molecule into an SVG *string* — no Qt involved. Keeping this in ``services``
means the identical depiction code will later feed PDF reports and docs, and it
is fully testable headlessly.

RDKit concepts
--------------
* **2D coordinates** — molecules parsed from SMILES have *no* atom positions;
  :func:`rdkit.Chem.rdDepictor.Compute2DCoords` generates a layout. Molecules
  from SDF/MOL files usually already carry 2D coordinates, which we keep.
* :func:`rdMolDraw2D.PrepareAndDrawMolecule` — handles kekulization, wedge
  bonds and highlighting the way the RDKit authors recommend.
* :func:`rdMolDraw2D.SetDarkMode` — switches the atom palette for dark
  backgrounds (black carbon lines are invisible on a dark theme).
* ``clearBackground = False`` — we draw on a *transparent* background so the
  depiction blends into whatever surface displays it.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from rdkit import Chem
from rdkit.Chem import rdDepictor
from rdkit.Chem.Draw import rdMolDraw2D

logger = logging.getLogger(__name__)


def _bonds_within(mol: Chem.Mol, atoms: set[int]) -> list[int]:
    """Return the ids of bonds whose *both* ends are in ``atoms``.

    Highlighting the connecting bonds as well as the atoms makes a matched
    substructure read as one solid region rather than scattered dots.
    """
    return [
        bond.GetIdx()
        for bond in mol.GetBonds()
        if bond.GetBeginAtomIdx() in atoms and bond.GetEndAtomIdx() in atoms
    ]


def _draw(
    drawer,  # noqa: ANN001 — a MolDraw2DSVG or MolDraw2DCairo
    mol: Chem.Mol,
    dark: bool,
    legend: str,
    highlight_atoms: Sequence[int] | None,
    *,
    transparent: bool,
) -> None:
    """Shared drawing body for the SVG and PNG renderers.

    Copies the molecule (never mutating the shared record), generates 2D
    coordinates if missing, applies the palette, and draws — optionally with a
    highlighted substructure.
    """
    work = Chem.Mol(mol)  # cheap copy; protects the shared record
    if work.GetNumConformers() == 0:
        rdDepictor.Compute2DCoords(work)

    options = drawer.drawOptions()
    if dark:
        rdMolDraw2D.SetDarkMode(options)
    if transparent:
        options.clearBackground = False  # blends into the display surface

    if highlight_atoms:
        atoms = list(highlight_atoms)
        rdMolDraw2D.PrepareAndDrawMolecule(
            drawer,
            work,
            legend=legend,
            highlightAtoms=atoms,
            highlightBonds=_bonds_within(work, set(atoms)),
        )
    else:
        rdMolDraw2D.PrepareAndDrawMolecule(drawer, work, legend=legend)
    drawer.FinishDrawing()


def render_svg(
    mol: Chem.Mol,
    width: int = 350,
    height: int = 280,
    dark: bool = False,
    legend: str = "",
    highlight_atoms: Sequence[int] | None = None,
) -> str:
    """Render ``mol`` as an SVG string of ``width`` × ``height`` pixels.

    The input molecule is never mutated: we draw a copy, generating 2D
    coordinates on it only if none exist (records are shared across the app,
    so mutating them here would be a hidden side effect).

    Parameters
    ----------
    mol:
        The molecule to depict.
    width, height:
        Logical canvas size in pixels (SVG scales losslessly afterwards).
    dark:
        Use RDKit's dark-mode palette (light bonds/atoms for dark backgrounds).
    legend:
        Optional caption drawn under the structure.
    highlight_atoms:
        Atom indices to highlight (e.g. a substructure match). The bonds between
        them are highlighted too, so the region reads as one piece. ``None`` or
        empty draws no highlight.

    Returns
    -------
    str
        The SVG document as text.

    """
    drawer = rdMolDraw2D.MolDraw2DSVG(width, height)
    _draw(drawer, mol, dark, legend, highlight_atoms, transparent=True)
    return drawer.GetDrawingText()


def render_png(
    mol: Chem.Mol,
    width: int = 350,
    height: int = 280,
    dark: bool = False,
    legend: str = "",
    highlight_atoms: Sequence[int] | None = None,
) -> bytes:
    """Render ``mol`` as PNG bytes, using RDKit's Cairo backend (no Qt).

    Used by the PDF report writer, which needs a raster image. The background is
    left opaque (white in light mode) because a report page is not transparent.
    The input molecule is never mutated. Parameters mirror :func:`render_svg`.
    """
    drawer = rdMolDraw2D.MolDraw2DCairo(width, height)
    _draw(drawer, mol, dark, legend, highlight_atoms, transparent=False)
    return drawer.GetDrawingText()
