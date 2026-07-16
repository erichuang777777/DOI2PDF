"""DOI2PDF: lawful, provenance-aware academic PDF retrieval."""

from .config import Settings
from .models import FetchResult
from .pipeline import DOI2PDF
from ._version import __version__

__all__ = ["DOI2PDF", "FetchResult", "Settings", "__version__"]
