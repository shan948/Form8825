"""Form 8825 document processing."""
from .errors import ExtractionError
from .extract import ExtractionResult, extract_8825, output_record

__all__ = ["extract_8825", "output_record", "ExtractionResult", "ExtractionError"]
