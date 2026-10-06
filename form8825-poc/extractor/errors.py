"""Typed errors so callers (CLI, API, tests) can react to each failure mode."""


class ExtractionError(Exception):
    """Base class. `code` is stable and safe to show in an API response."""

    code = "extraction_error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class InputFileError(ExtractionError):
    code = "input_file_error"          # missing, empty, too large, unreadable


class NotAPdfError(ExtractionError):
    code = "not_a_pdf"                 # wrong magic bytes (e.g. a renamed .docx)


class CorruptPdfError(ExtractionError):
    code = "corrupt_pdf"               # truncated / broken xref / parser failure


class EncryptedPdfError(ExtractionError):
    code = "encrypted_pdf"             # needs a password we don't have


class NotForm8825Error(ExtractionError):
    code = "not_form_8825"             # valid PDF but no 8825 page found


class OcrUnavailableError(ExtractionError):
    code = "ocr_unavailable"           # scanned input but tesseract isn't installed


class NoTextLayerError(ExtractionError):
    code = "no_text_layer"             # scanned input and OCR was disabled by the caller


class NoDataFoundError(ExtractionError):
    code = "no_data_found"             # 8825 page found but every cell is empty
