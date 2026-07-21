"""Standardization-reproducibility auditing (the research flagship).

Structure standardization is mandatory but under-specified: different protocols —
and different settings within one toolkit — produce different "standard"
structures for the same input, so a molecule's identity can silently depend on
the pipeline. This package treats that *divergence* as a first-class, quantified
diagnostic.

R1 provides the **protocol engine**: a named, composable
:class:`~wawekit.services.reproducibility.protocol.StandardizationProtocol`, a set
of presets, and the primitives to apply a protocol and take a molecule's standard
identity (InChIKey). R2 adds **divergence analysis** (do protocols agree, and via
ablation, *why not*). R3 adds **dataset-level metrics** (reproducibility score,
pairwise agreement, cause spectrum). Later stages build the GUI panel and
benchmark on top.
"""

from wawekit.services.reproducibility.divergence import (
    DivergenceRun,
    MoleculeDivergence,
    analyze_divergence,
    analyze_molecule,
)
from wawekit.services.reproducibility.metrics import (
    ProtocolPairAgreement,
    ReproducibilityMetrics,
    compute_metrics,
)
from wawekit.services.reproducibility.protocol import (
    DEFAULT_PROTOCOLS,
    OPERATION_ORDER,
    PRESET_AGGRESSIVE,
    PRESET_CHEMBL_LIKE,
    PRESET_MINIMAL,
    StandardForm,
    StandardizationProtocol,
    StandardOp,
    apply_protocol,
    standard_identity,
    standardize,
)

__all__ = [
    "DEFAULT_PROTOCOLS",
    "OPERATION_ORDER",
    "PRESET_AGGRESSIVE",
    "PRESET_CHEMBL_LIKE",
    "PRESET_MINIMAL",
    "DivergenceRun",
    "MoleculeDivergence",
    "ProtocolPairAgreement",
    "ReproducibilityMetrics",
    "StandardForm",
    "StandardOp",
    "StandardizationProtocol",
    "analyze_divergence",
    "analyze_molecule",
    "apply_protocol",
    "compute_metrics",
    "standard_identity",
    "standardize",
]
