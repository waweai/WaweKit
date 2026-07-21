"""Composable standardization protocols and the engine that runs them.

A **protocol** is a named set of normalization *operations* applied in a fixed,
chemically-sensible order. Modelling standardization as toggleable operations —
rather than one opaque "standardize" call — is what makes the reproducibility
study possible: two protocols can be compared, and a divergence can later be
*attributed* to a specific operation by toggling it (ablation).

Operations (applied in :data:`OPERATION_ORDER`)
-----------------------------------------------
* ``METAL_DISCONNECT`` — break covalent metal–organic bonds (``MetalDisconnector``).
* ``NORMALIZE`` — canonicalise functional-group representations (``Normalizer``).
* ``REIONIZE`` — move protons to the correct atoms (``Reionizer``).
* ``FRAGMENT_PARENT`` — keep the largest organic fragment, dropping salts/solvents.
* ``UNCHARGE`` — neutralise charges where chemically sensible (``Uncharger``).
* ``REMOVE_ISOTOPES`` — clear isotope labels.
* ``REMOVE_STEREO`` — flatten stereochemistry.
* ``CANONICAL_TAUTOMER`` — pick RDKit's canonical tautomer (the most contentious,
  and the operation the ChEMBL-style protocol deliberately omits).

Identity
--------
Two standardized structures are "the same" iff their **InChIKey** matches — the
field-standard identity. That is what protocol *agreement* is measured on.

Qt-free, so the whole engine runs in a benchmark harness or a notebook.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from enum import StrEnum
from functools import lru_cache

from rdkit import Chem, rdBase
from rdkit.Chem.MolStandardize import rdMolStandardize

logger = logging.getLogger(__name__)


class StandardOp(StrEnum):
    """One toggleable standardization operation."""

    METAL_DISCONNECT = "metal_disconnect"
    NORMALIZE = "normalize"
    REIONIZE = "reionize"
    FRAGMENT_PARENT = "fragment_parent"
    UNCHARGE = "uncharge"
    REMOVE_ISOTOPES = "remove_isotopes"
    REMOVE_STEREO = "remove_stereo"
    CANONICAL_TAUTOMER = "canonical_tautomer"


#: The order operations are applied in — the only order that makes chemical sense
#: (disconnect/normalise/reionise before choosing a parent, tautomer last).
OPERATION_ORDER: tuple[StandardOp, ...] = (
    StandardOp.METAL_DISCONNECT,
    StandardOp.NORMALIZE,
    StandardOp.REIONIZE,
    StandardOp.FRAGMENT_PARENT,
    StandardOp.UNCHARGE,
    StandardOp.REMOVE_ISOTOPES,
    StandardOp.REMOVE_STEREO,
    StandardOp.CANONICAL_TAUTOMER,
)


@dataclass(frozen=True)
class _Helpers:
    """Reusable rdMolStandardize helper objects (some are costly to build)."""

    metal: object
    normalizer: object
    reionizer: object
    fragment: object
    uncharger: object
    tautomer: object


@lru_cache(maxsize=1)
def _helpers() -> _Helpers:
    """Construct the standardization helpers once (TautomerEnumerator is slow)."""
    return _Helpers(
        metal=rdMolStandardize.MetalDisconnector(),
        normalizer=rdMolStandardize.Normalizer(),
        reionizer=rdMolStandardize.Reionizer(),
        fragment=rdMolStandardize.LargestFragmentChooser(),
        uncharger=rdMolStandardize.Uncharger(),
        tautomer=rdMolStandardize.TautomerEnumerator(),
    )


def _op_metal(mol: Chem.Mol) -> Chem.Mol:
    return _helpers().metal.Disconnect(mol)


def _op_normalize(mol: Chem.Mol) -> Chem.Mol:
    return _helpers().normalizer.normalize(mol)


def _op_reionize(mol: Chem.Mol) -> Chem.Mol:
    return _helpers().reionizer.reionize(mol)


def _op_fragment(mol: Chem.Mol) -> Chem.Mol:
    return _helpers().fragment.choose(mol)


def _op_uncharge(mol: Chem.Mol) -> Chem.Mol:
    return _helpers().uncharger.uncharge(mol)


def _op_remove_isotopes(mol: Chem.Mol) -> Chem.Mol:
    for atom in mol.GetAtoms():
        atom.SetIsotope(0)
    return mol


def _op_remove_stereo(mol: Chem.Mol) -> Chem.Mol:
    Chem.RemoveStereochemistry(mol)
    return mol


def _op_tautomer(mol: Chem.Mol) -> Chem.Mol:
    return _helpers().tautomer.Canonicalize(mol)


#: Operation → the function that applies it.
_OP_FUNCS = {
    StandardOp.METAL_DISCONNECT: _op_metal,
    StandardOp.NORMALIZE: _op_normalize,
    StandardOp.REIONIZE: _op_reionize,
    StandardOp.FRAGMENT_PARENT: _op_fragment,
    StandardOp.UNCHARGE: _op_uncharge,
    StandardOp.REMOVE_ISOTOPES: _op_remove_isotopes,
    StandardOp.REMOVE_STEREO: _op_remove_stereo,
    StandardOp.CANONICAL_TAUTOMER: _op_tautomer,
}


@dataclass(frozen=True, slots=True)
class StandardizationProtocol:
    """A named set of standardization operations.

    Attributes
    ----------
    name:
        Human-readable identifier (used in reports and as a dict key).
    operations:
        Which operations are enabled. They always run in
        :data:`OPERATION_ORDER`, so the set — not an order — defines a protocol.

    """

    name: str
    operations: frozenset[StandardOp]

    def applied_ops(self) -> list[StandardOp]:
        """Return the enabled operations in canonical application order."""
        return [op for op in OPERATION_ORDER if op in self.operations]

    def has(self, op: StandardOp) -> bool:
        """Return whether ``op`` is enabled."""
        return op in self.operations

    def with_op(self, op: StandardOp, enabled: bool) -> StandardizationProtocol:
        """Return a copy with ``op`` toggled — the primitive ablation uses.

        The name gains a ``+op`` / ``-op`` suffix so an ablated protocol is
        identifiable in a report.
        """
        ops = set(self.operations)
        if enabled:
            ops.add(op)
            suffix = f"+{op.value}"
        else:
            ops.discard(op)
            suffix = f"-{op.value}"
        return replace(self, name=f"{self.name}{suffix}", operations=frozenset(ops))

    @property
    def label(self) -> str:
        """Short description, e.g. ``ChEMBL-like (5 ops)``."""
        return f"{self.name} ({len(self.operations)} op{'s' if len(self.operations) != 1 else ''})"


#: Sanitize + normalise only — the raw floor most people apply.
PRESET_MINIMAL = StandardizationProtocol(
    name="Minimal",
    operations=frozenset({StandardOp.NORMALIZE}),
)

#: Approximates the ChEMBL structure pipeline: disconnect metals, normalise,
#: reionise, keep the parent fragment, neutralise — but *no* tautomer canonicalisation.
PRESET_CHEMBL_LIKE = StandardizationProtocol(
    name="ChEMBL-like",
    operations=frozenset(
        {
            StandardOp.METAL_DISCONNECT,
            StandardOp.NORMALIZE,
            StandardOp.REIONIZE,
            StandardOp.FRAGMENT_PARENT,
            StandardOp.UNCHARGE,
        }
    ),
)

#: Everything, including tautomer canonicalisation and stripping stereo/isotopes.
PRESET_AGGRESSIVE = StandardizationProtocol(
    name="Aggressive",
    operations=frozenset(OPERATION_ORDER),
)

#: The default protocol set compared in a reproducibility run.
DEFAULT_PROTOCOLS: tuple[StandardizationProtocol, ...] = (
    PRESET_MINIMAL,
    PRESET_CHEMBL_LIKE,
    PRESET_AGGRESSIVE,
)


@dataclass(frozen=True, slots=True)
class StandardForm:
    """The result of standardizing one molecule with one protocol.

    Attributes
    ----------
    protocol:
        Name of the protocol used.
    smiles:
        Canonical SMILES of the standardized structure (``""`` on failure).
    inchikey:
        InChIKey identity of the standardized structure (``""`` on failure) —
        what protocol *agreement* is measured on.
    error:
        Failure message, or ``None`` on success.

    """

    protocol: str
    smiles: str
    inchikey: str
    error: str | None = None

    @property
    def ok(self) -> bool:
        """Whether standardization succeeded and produced an identity."""
        return self.error is None and bool(self.inchikey)


def apply_protocol(mol: Chem.Mol, protocol: StandardizationProtocol) -> Chem.Mol:
    """Apply ``protocol``'s operations to a copy of ``mol`` and return it.

    The input is never mutated. May raise if RDKit rejects an intermediate.
    """
    work = Chem.Mol(mol)  # never mutate the shared record
    Chem.SanitizeMol(work)
    for op in protocol.applied_ops():
        work = _OP_FUNCS[op](work)
    Chem.SanitizeMol(work)
    return work


def standard_identity(mol: Chem.Mol) -> str:
    """Return ``mol``'s InChIKey, or ``""`` if it cannot be computed.

    RDKit's InChI layer writes to stderr on odd structures; we mute it and treat
    a missing key as "no identity" rather than an error.
    """
    with rdBase.BlockLogs():
        return Chem.MolToInchiKey(mol) or ""


def standardize(mol: Chem.Mol, protocol: StandardizationProtocol) -> StandardForm:
    """Standardize ``mol`` with ``protocol`` and return its :class:`StandardForm`.

    Never raises: a molecule RDKit cannot process yields a ``StandardForm`` whose
    ``error`` is set, so a divergence run over a whole dataset cannot be aborted
    by one pathological structure.
    """
    try:
        std = apply_protocol(mol, protocol)
        return StandardForm(
            protocol=protocol.name,
            smiles=Chem.MolToSmiles(std),
            inchikey=standard_identity(std),
        )
    except Exception as exc:  # noqa: BLE001 — one bad molecule must not abort a run
        logger.debug("Protocol %s failed on a molecule: %s", protocol.name, exc)
        return StandardForm(protocol=protocol.name, smiles="", inchikey="", error=str(exc))
