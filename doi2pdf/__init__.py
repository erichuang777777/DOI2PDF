"""DOI2PDF: lawful, provenance-aware academic PDF retrieval."""

from .config import Settings
from .models import FetchResult
from .pipeline import DOI2PDF

__all__ = ["DOI2PDF", "FetchResult", "Settings"]
__version__ = "0.1.0"
