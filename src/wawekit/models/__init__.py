"""Domain models — RDKit-backed objects representing molecules and results.

This layer holds the toolkit's *science data*. It must stay free of any Qt
import so it can be unit-tested and reused headlessly (CLI, notebooks, batch
pipelines).
"""

from wawekit.models.molecule import MoleculeRecord

__all__ = ["MoleculeRecord"]
