"""Quality-hardened scientific document ingestion.

This package only creates candidate review artifacts.  It has no promotion,
approval, production retrieval, or execution API.
"""

from .pipeline import ScientificDocumentIngestionService

__all__ = ["ScientificDocumentIngestionService"]
