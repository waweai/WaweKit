"""Standardizers: anything that maps a molecule to a standardized identity.

The protocol engine (:mod:`.protocol`) models standardization as a composition
of individually toggleable RDKit operations. That is what makes ablation-based
cause attribution possible, but it also confines comparison to protocols *we*
construct — and the disagreement that matters in practice is between the
production pipelines different databases actually run.

This module widens the comparison. A :class:`Standardizer` is anything that
turns a molecule into a
:class:`~wawekit.services.reproducibility.protocol.StandardForm`; a composed
RDKit protocol is one kind, and a third-party pipeline invoked as a black box
is another. Divergence measurement works over any mixture of them.

The cost of that generality is stated by
:attr:`Standardizer.is_ablatable`. Cause attribution requires being able to
disable one operation and re-run, which an opaque external pipeline does not
allow. Mixed comparisons therefore still report *whether* standardizers
disagree, but can only attribute *why* for the composable ones — and the
distinction is exposed rather than hidden, so a caller never receives an empty
cause list that looks like "no cause found" when it means "cannot attribute".

Optional dependencies
---------------------
The external adapters require packages that are not core dependencies:
``chembl_structure_pipeline`` and ``molvs``. Each adapter reports its own
availability through :func:`available_standardizers`, so a caller can offer
whichever are installed without importing the rest.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from rdkit import Chem

from wawekit.services.reproducibility.protocol import (
    StandardForm,
    StandardizationProtocol,
    standard_identity,
)
from wawekit.services.reproducibility.protocol import (
    standardize as apply_rdkit_protocol,
)

logger = logging.getLogger(__name__)


@runtime_checkable
class Standardizer(Protocol):
    """Anything that produces a standardized identity for a molecule."""

    name: str

    def standardize_mol(self, mol: Chem.Mol) -> StandardForm:
        """Return the standardized form, never raising."""
        ...

    @property
    def is_ablatable(self) -> bool:
        """Whether individual operations can be disabled for cause attribution."""
        ...


class ProtocolStandardizer:
    """Adapts a composed RDKit :class:`StandardizationProtocol`.

    The only standardizer kind that supports ablation, because it is the only
    one whose operations are individually addressable.
    """

    def __init__(self, protocol: StandardizationProtocol) -> None:
        self.protocol = protocol
        self.name = protocol.name

    def standardize_mol(self, mol: Chem.Mol) -> StandardForm:
        """Standardize via the composed protocol."""
        return apply_rdkit_protocol(mol, self.protocol)

    @property
    def is_ablatable(self) -> bool:
        """Composed protocols expose their operations, so ablation applies."""
        return True


class _ExternalStandardizer:
    """Base for third-party pipelines invoked as black boxes.

    Subclasses implement :meth:`_run`, which may raise; failures are converted
    to a ``StandardForm`` carrying the error, matching the discipline of the
    rest of the package — one unprocessable molecule must not abort a run.
    """

    name = "external"

    def _run(self, mol: Chem.Mol) -> Chem.Mol:
        raise NotImplementedError

    def standardize_mol(self, mol: Chem.Mol) -> StandardForm:
        """Run the external pipeline, converting any failure into a StandardForm."""
        try:
            result = self._run(Chem.Mol(mol))  # never mutate the caller's molecule
            return StandardForm(
                protocol=self.name,
                smiles=Chem.MolToSmiles(result),
                inchikey=standard_identity(result),
            )
        except Exception as exc:  # noqa: BLE001 — boundary around third-party code
            logger.debug("%s failed on a molecule: %s", self.name, exc)
            return StandardForm(protocol=self.name, smiles="", inchikey="", error=str(exc))

    @property
    def is_ablatable(self) -> bool:
        """External pipelines are opaque: their steps cannot be toggled."""
        return False


class ChEMBLPipelineStandardizer(_ExternalStandardizer):
    """ChEMBL's production structure-curation pipeline.

    Runs the two documented stages in order — ``standardize_mol`` followed by
    ``get_parent_mol`` — which together produce the parent structure ChEMBL
    registers. This is the same code the database itself runs, so a comparison
    against it measures real disagreement rather than an approximation of one.
    """

    name = "ChEMBL pipeline"

    def _run(self, mol: Chem.Mol) -> Chem.Mol:
        from chembl_structure_pipeline import get_parent_mol, standardizer

        standardized = standardizer.standardize_mol(mol)
        parent, _ = get_parent_mol(standardized)
        return parent


class MolVSStandardizer(_ExternalStandardizer):
    """MolVS, a widely used configurable standardizer.

    Two configurations are offered because MolVS's own defaults draw the line
    differently from ChEMBL's: ``standardize()`` normalizes without removing
    salts, whereas ``super_parent()`` additionally strips fragments, charge,
    isotopes and stereochemistry. Comparing them shows that configuration
    *within* one tool can matter as much as the choice *between* tools.
    """

    def __init__(self, super_parent: bool = False) -> None:
        self.super_parent = super_parent
        self.name = "MolVS super-parent" if super_parent else "MolVS default"

    def _run(self, mol: Chem.Mol) -> Chem.Mol:
        from molvs import Standardizer

        standardizer = Standardizer()
        if self.super_parent:
            return standardizer.super_parent(mol)
        return standardizer.standardize(mol)


def _importable(module: str) -> bool:
    """Whether an optional dependency can be imported."""
    from importlib.util import find_spec

    try:
        return find_spec(module) is not None
    except (ImportError, ValueError):  # pragma: no cover — malformed install
        return False


def available_standardizers() -> dict[str, bool]:
    """Report which external standardizers this installation can offer."""
    return {
        "ChEMBL pipeline": _importable("chembl_structure_pipeline"),
        "MolVS": _importable("molvs"),
    }


def external_standardizers() -> list[Standardizer]:
    """Return an instance of every external standardizer that is installed."""
    found: list[Standardizer] = []
    if _importable("chembl_structure_pipeline"):
        found.append(ChEMBLPipelineStandardizer())
    if _importable("molvs"):
        found.append(MolVSStandardizer(super_parent=False))
        found.append(MolVSStandardizer(super_parent=True))
    return found
