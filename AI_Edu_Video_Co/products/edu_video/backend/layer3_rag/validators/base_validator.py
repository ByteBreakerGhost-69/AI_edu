# products/edu_video/backend/layer3_rag/validators/base_validator.py
"""
Abstract base class for all domain content validators.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from enum import StrEnum

import structlog
from pydantic import BaseModel

from core.utils import utcnow

__all__ = [
    "BaseValidator",
    "ValidationReport",
    "ValidationIssue",
    "ValidationSeverity",
    "register_validator",
    "ValidatorRegistry",
]

logger = structlog.get_logger(__name__)

ValidatorRegistry: dict[str, type["BaseValidator"]] = {}


def register_validator(name: str):
    """Class decorator factory — registers validator into ValidatorRegistry."""
    def decorator(cls: type["BaseValidator"]) -> type["BaseValidator"]:
        ValidatorRegistry[name] = cls
        logger.debug("validator_registered", name=name, cls=cls.__name__)
        return cls
    return decorator


class ValidationSeverity(StrEnum):
    ERROR = "error"      # blocks content — must fix before publish
    WARNING = "warning"  # flags for human review — pipeline continues
    INFO = "info"        # informational — no action required


class ValidationIssue(BaseModel):
    severity: ValidationSeverity
    code: str
    message: str
    location: str
    suggestion: str


class ValidationReport(BaseModel):
    is_valid: bool
    issues: list[ValidationIssue]
    validated_at: datetime
    validator_name: str
    confidence: float


class BaseValidator(ABC):
    """
    Abstract base for domain validators.
    Subclasses implement validate() and validator_name.
    Never raise — catch all exceptions and return a report with ERROR issue.
    """

    @property
    @abstractmethod
    def validator_name(self) -> str: ...

    @abstractmethod
    async def validate(
        self,
        content: str,
        context: dict,
    ) -> ValidationReport: ...

    def _make_report(
        self,
        issues: list[ValidationIssue],
        confidence: float,
    ) -> ValidationReport:
        is_valid = not any(
            i.severity == ValidationSeverity.ERROR for i in issues
        )
        return ValidationReport(
            is_valid=is_valid,
            issues=issues,
            validated_at=utcnow(),
            validator_name=self.validator_name,
            confidence=confidence,
        )

    def _error(
        self, code: str, message: str, location: str, suggestion: str
    ) -> ValidationIssue:
        return ValidationIssue(
            severity=ValidationSeverity.ERROR,
            code=code,
            message=message,
            location=location,
            suggestion=suggestion,
        )

    def _warning(
        self, code: str, message: str, location: str, suggestion: str
    ) -> ValidationIssue:
        return ValidationIssue(
            severity=ValidationSeverity.WARNING,
            code=code,
            message=message,
            location=location,
            suggestion=suggestion,
        )

    def _info(
        self, code: str, message: str, location: str, suggestion: str = ""
    ) -> ValidationIssue:
        return ValidationIssue(
            severity=ValidationSeverity.INFO,
            code=code,
            message=message,
            location=location,
            suggestion=suggestion,
        )

    def _crash_report(self, error: str) -> ValidationReport:
        """Safe report returned from except blocks."""
        return self._make_report(
            issues=[
                self._error(
                    code="validator_crashed",
                    message=f"Validator failed internally: {error}",
                    location="unknown",
                    suggestion="Check validator logs and retry.",
                )
            ],
            confidence=0.0,
)
