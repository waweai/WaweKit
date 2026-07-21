"""Molecular fingerprint computation.

Fingerprints turn structures into fixed-length bit vectors so that similarity
becomes a bitwise operation. This service builds them and caches the result on
each record.

RDKit: use the *generator* API
------------------------------
Most tutorials still teach ``AllChem.GetMorganFingerprintAsBitVect(mol, 2,
nBits=2048)``. In RDKit 2026.03 that call prints
``DEPRECATION WARNING: please use MorganGenerator``. The current API is
:mod:`rdkit.Chem.rdFingerprintGenerator`: build a generator once, then call
``GetFingerprint(mol)`` per molecule.

That shape is also the *performance* lesson from Module 4, restated: the
generator is the expensive object, so :func:`_bit_vector_builder` constructs it
**once per run** and returns a plain callable the loop reuses. Building a
generator per molecule would dominate runtime on a large set.

MACCS is the exception — it has no generator and no parameters; it is a fixed
set of 166 predefined structural keys, so ``MACCSkeys.GenMACCSKeys`` *is* the
callable.

Design rules (identical seam to descriptors and standardization):

* **Qt-free** — a plain ``progress`` callback.
* **A report, not just results** — counts and per-molecule failures as data.
* **One bad molecule never aborts the run.**
* **Cached in place** — a fingerprint derives from the structure and changes
  nothing about it, so like descriptors it fills a cache slot on the record
  rather than producing new records.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from rdkit import Chem
from rdkit.Chem import MACCSkeys
from rdkit.Chem import rdFingerprintGenerator as rfg
from rdkit.DataStructs.cDataStructs import ExplicitBitVect

from wawekit.models.fingerprints import Fingerprint, FingerprintKind, FingerprintOptions
from wawekit.models.molecule import MoleculeRecord
from wawekit.services.io.molecule_loader import ProgressCallback

logger = logging.getLogger(__name__)

#: A function that turns one molecule into a bit vector.
BitVectorBuilder = Callable[[Chem.Mol], ExplicitBitVect]


@dataclass(slots=True)
class FingerprintReport:
    """Outcome of a fingerprint run.

    Attributes
    ----------
    records:
        The records the run covered (the same objects passed in — fingerprints
        are cached on them in place).
    options:
        The normalized options every computed fingerprint used.
    computed:
        How many fingerprints were calculated this run.
    reused:
        How many records already carried a fingerprint with matching options.
    failures:
        ``"name: message"`` per molecule RDKit could not handle.

    """

    options: FingerprintOptions
    records: list[MoleculeRecord] = field(default_factory=list)
    computed: int = 0
    reused: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def n_records(self) -> int:
        """Number of records covered by the run."""
        return len(self.records)

    @property
    def n_failed(self) -> int:
        """Number of molecules whose fingerprint could not be computed."""
        return len(self.failures)


def _bit_vector_builder(options: FingerprintOptions) -> BitVectorBuilder:
    """Build the per-molecule fingerprint function **once** for a whole run.

    Returns a callable rather than branching inside the loop: the generator is
    the costly object, and constructing it per molecule would dominate runtime.
    """
    match options.kind:
        case FingerprintKind.MACCS:
            # No generator, no parameters — the keys are a fixed pattern list.
            return MACCSkeys.GenMACCSKeys
        case FingerprintKind.RDKIT:
            return rfg.GetRDKitFPGenerator(fpSize=options.n_bits).GetFingerprint
        case _:
            invariants = rfg.GetMorganFeatureAtomInvGen() if options.use_features else None
            generator = rfg.GetMorganGenerator(
                radius=options.radius,
                fpSize=options.n_bits,
                atomInvariantsGenerator=invariants,
            )
            return generator.GetFingerprint


def compute_fingerprint(mol: Chem.Mol, options: FingerprintOptions) -> Fingerprint:
    """Compute the fingerprint of one molecule.

    Convenience for single-molecule callers (tests, notebooks). Building a
    dataset? Use :func:`compute_fingerprints`, which reuses one generator.

    Parameters
    ----------
    mol:
        A sanitized RDKit molecule.
    options:
        How to build the fingerprint.

    Returns
    -------
    Fingerprint
        The bit vector plus the normalized options that produced it.

    """
    normalized = options.normalized()
    return Fingerprint(bits=_bit_vector_builder(normalized)(mol), options=normalized)


def compute_fingerprints(
    records: list[MoleculeRecord],
    options: FingerprintOptions | None = None,
    recompute: bool = False,
    progress: ProgressCallback | None = None,
) -> FingerprintReport:
    """Compute and cache fingerprints across ``records``.

    A record is skipped only if it already carries a fingerprint built with the
    *same* options — mismatched parameters are recomputed rather than left
    mixed, because vectors from different parameters are not comparable.

    Parameters
    ----------
    records:
        Dataset to process. Each record's ``fingerprint`` field is filled in
        place; nothing else about the record is touched.
    options:
        How to build the fingerprints (defaults to Morgan r2 / 2048 bits).
    recompute:
        Recalculate even where a matching fingerprint is already cached.
    progress:
        Optional ``(done, total)`` callback (safe to pass a signal's ``emit``).

    Returns
    -------
    FingerprintReport
        Counts, the options used, and any per-molecule failures.

    """
    normalized = (options or FingerprintOptions()).normalized()
    report = FingerprintReport(options=normalized, records=list(records))
    build = _bit_vector_builder(normalized)  # once per run, not per molecule
    total = len(records)
    logger.info(
        "Computing %s fingerprints for %d record(s) (recompute=%s)",
        normalized.label,
        total,
        recompute,
    )

    for done, record in enumerate(records, start=1):
        cached = record.fingerprint
        if cached is not None and cached.options == normalized and not recompute:
            report.reused += 1
        else:
            try:
                record.fingerprint = Fingerprint(bits=build(record.mol), options=normalized)
                report.computed += 1
            except Exception as exc:  # noqa: BLE001 — one bad molecule must not abort the run
                logger.exception("Fingerprint computation failed for %s", record.name)
                report.failures.append(f"{record.name}: {exc}")
        if progress is not None:
            progress(done, total)

    logger.info(
        "Fingerprints complete: %d computed, %d reused, %d failure(s)",
        report.computed,
        report.reused,
        report.n_failed,
    )
    return report
