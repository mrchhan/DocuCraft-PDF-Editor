"""Exception types shared by the DocuCraft engine (no Qt imports).

`user_message` is always safe and meaningful to show to end users; `detail` holds
technical information for the log only.
"""
from __future__ import annotations


class DocuCraftError(Exception):
    def __init__(self, user_message: str = "", *, detail: str = ""):
        super().__init__(user_message)
        self.user_message = user_message
        self.detail = detail


class InvalidFileError(DocuCraftError):
    """File is missing, wrong type, unreadable, or too large."""


class InvalidPdfError(InvalidFileError):
    """Malformed or corrupted PDF that cannot be opened safely."""


class PasswordRequiredError(DocuCraftError):
    """The PDF is encrypted and needs a password."""


class WrongPasswordError(DocuCraftError):
    """The supplied password did not open the PDF."""


class OverwriteNotConfirmed(DocuCraftError):
    """An operation would replace an existing file without explicit confirmation."""


class ResourceLimitError(InvalidFileError):
    """Document exceeds safe processing limits."""


class DependencyMissingError(DocuCraftError):
    """An external tool (LibreOffice, Tesseract) was not found."""


class ConversionError(DocuCraftError):
    """A conversion failed."""


class OperationCancelled(DocuCraftError):
    """The user cancelled a running operation."""

    def __init__(self, user_message: str = "Operation cancelled."):
        super().__init__(user_message)


# short aliases
PasswordRequired = PasswordRequiredError
WrongPassword = WrongPasswordError
DependencyMissing = DependencyMissingError
