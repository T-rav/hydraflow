"""Pre-review validation for ADRs — catches structural defects before council."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class ADRValidationIssue:
    """A single validation issue found in an ADR."""

    code: str
    message: str
    fixable: bool = False


@dataclass
class ADRValidationResult:
    """Result of pre-review validation."""

    issues: list[ADRValidationIssue] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return len(self.issues) == 0

    @property
    def has_fixable_only(self) -> bool:
        return len(self.issues) > 0 and all(i.fixable for i in self.issues)


_STATUS_RE = re.compile(r"\*\*Status:\*\*\s*(\w+)", re.IGNORECASE)
_SUPERSEDE_RE = re.compile(
    r"supersed(?:es?|ed|ing)\s+(?:ADR[- ]?)(\d{4})", re.IGNORECASE
)
_REQUIRED_SECTIONS = ("## Context", "## Decision", "## Consequences")

# Matches ADR-NNNN references. Group 1 = the 4-digit number.
_ADR_REF_RE = re.compile(r"ADR[- ](\d{4})")

# Matches an ADR-NNNN reference that is followed by a title annotation:
#   ADR-0006 (Title)          — parenthesized title
#   ADR-0006 — Title          — em-dash title
#   ADR-0006: Title           — heading-style (only in # headings)
_ADR_REF_WITH_TITLE_RE = re.compile(r"ADR[- ]\d{4}\s*(?:\(|—)")


class ADRPreValidator:
    """Validates ADR structure before sending to the council."""

    def validate(
        self,
        content: str,
        all_adrs: list[tuple[int, str, str, str]] | None = None,
    ) -> ADRValidationResult:
        """Run all validation checks on an ADR.

        Args:
            content: The full markdown content of the ADR.
            all_adrs: Optional list of (number, title, content, filename) for cross-reference checks.

        Returns:
            ADRValidationResult with any issues found.
        """
        result = ADRValidationResult()
        self._check_status_field(content, result)
        self._check_required_sections(content, result)
        self._check_empty_sections(content, result)
        self._check_supersession(content, all_adrs or [], result)
        self._check_bare_adr_references(content, result)
        return result

    def _check_status_field(self, content: str, result: ADRValidationResult) -> None:
        """Check that the Status field exists and is a known value."""
        match = _STATUS_RE.search(content)
        if not match:
            result.issues.append(
                ADRValidationIssue(
                    code="missing_status",
                    message="ADR is missing a **Status:** field",
                    fixable=True,
                )
            )

    def _check_required_sections(
        self, content: str, result: ADRValidationResult
    ) -> None:
        """Check that all required sections are present."""
        for section in _REQUIRED_SECTIONS:
            if not re.search(
                rf"^{re.escape(section)}\s*$", content, re.IGNORECASE | re.MULTILINE
            ):
                result.issues.append(
                    ADRValidationIssue(
                        code=f"missing_section_{section.replace('## ', '').lower()}",
                        message=f"ADR is missing required section: {section}",
                        fixable=False,
                    )
                )

    def _check_empty_sections(self, content: str, result: ADRValidationResult) -> None:
        """Check that required sections have non-trivial content."""
        for section in _REQUIRED_SECTIONS:
            pattern = re.compile(
                rf"^{re.escape(section)}[ \t]*\n(.*?)(?=^##\s|\Z)",
                re.DOTALL | re.MULTILINE | re.IGNORECASE,
            )
            match = pattern.search(content)
            if match:
                body = match.group(1).strip()
                if not body:
                    section_name = section.replace("## ", "")
                    result.issues.append(
                        ADRValidationIssue(
                            code=f"empty_section_{section_name.lower()}",
                            message=f"Section '{section_name}' is present but empty",
                            fixable=False,
                        )
                    )

    def _check_supersession(
        self,
        content: str,
        all_adrs: list[tuple[int, str, str, str]],
        result: ADRValidationResult,
    ) -> None:
        """Check that supersession references point to existing ADRs."""
        matches = _SUPERSEDE_RE.findall(content)
        if not matches:
            return

        existing_numbers = {num for num, *_ in all_adrs}
        for ref_str in matches:
            ref_num = int(ref_str)
            if ref_num not in existing_numbers:
                result.issues.append(
                    ADRValidationIssue(
                        code="invalid_supersession",
                        message=(
                            f"ADR references superseding ADR-{ref_num:04d} "
                            f"but that ADR does not exist"
                        ),
                        fixable=False,
                    )
                )

    def _check_bare_adr_references(
        self,
        content: str,
        result: ADRValidationResult,
    ) -> None:
        """Check that ADR cross-references include the referenced ADR's title.

        Bare references like ``ADR-0006`` are opaque; the reader cannot tell
        what the referenced ADR covers without opening it.  Each cross-reference
        should include the title in parentheses — e.g. ``ADR-0006 (RepoRuntime
        Isolation Architecture)`` — or after an em-dash.

        Exceptions: the ADR's own heading line (``# ADR-NNNN: Title``) and
        markdown table rows (which may contain example/illustration text).
        """
        # Extract self-number from the heading to skip self-references
        heading_match = re.search(r"^#\s+ADR[- ](\d{4})", content, re.MULTILINE)
        self_number = heading_match.group(1) if heading_match else None

        bare_numbers: set[str] = set()
        for line in content.splitlines():
            # Skip heading lines (contain the ADR's own title after ':')
            if line.lstrip().startswith("#"):
                continue
            # Skip markdown table rows (may contain example text)
            if "|" in line:
                continue

            for match in _ADR_REF_RE.finditer(line):
                ref_num = match.group(1)
                # Skip self-references
                if ref_num == self_number:
                    continue
                # Check if this specific occurrence has a title annotation
                # Look at the text starting from this match position
                rest = line[match.start() :]
                if not _ADR_REF_WITH_TITLE_RE.match(rest):
                    bare_numbers.add(ref_num)

        for ref_num in sorted(bare_numbers):
            result.issues.append(
                ADRValidationIssue(
                    code="bare_adr_reference",
                    message=(
                        f"ADR-{ref_num} is referenced without its title. "
                        f"Add the title in parentheses, e.g. "
                        f"ADR-{ref_num} (Title Here)"
                    ),
                    fixable=True,
                )
            )
