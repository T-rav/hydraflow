"""HITL tab — human-in-the-loop items awaiting corrections."""

from __future__ import annotations

from .base import BasePage


class HitlPage(BasePage):
    async def open(self) -> None:
        """Navigate to the merged Outcomes surface where HITL items render.

        HITL no longer has a standalone tab — items render at the top of the
        Outcomes tab (see ``src/ui/src/App.jsx``). The React app's
        ``_initialTabFromUrl()`` reads the ``tab`` URL parameter and redirects
        the old ``?tab=hitl`` deep link to ``outcomes``, so navigating there
        directly lands on the right view without any tab click.
        """
        await self.goto("/?tab=hitl")

    def item(self, issue_number: int):
        """Row element for a HITL item (click to expand detail panel)."""
        return self.page.locator(f'[data-testid="hitl-row-{issue_number}"]')

    def detail(self, issue_number: int):
        """Expanded detail panel for a HITL item."""
        return self.page.locator(f'[data-testid="hitl-detail-{issue_number}"]')

    def correction_input(self, issue_number: int):
        """Correction textarea inside the expanded detail panel."""
        return self.page.locator(f'[data-testid="hitl-textarea-{issue_number}"]')

    def submit_button(self, issue_number: int):
        """'Retry with guidance' button — submits correction to /api/hitl/{N}/correct."""
        return self.page.locator(f'[data-testid="hitl-retry-{issue_number}"]')

    def skip_button(self, issue_number: int):
        """Skip button — posts **HITL Skip** comment and removes item from queue."""
        return self.page.locator(f'[data-testid="hitl-skip-{issue_number}"]')

    def close_button(self, issue_number: int):
        """Close button — posts **HITL Close** comment and closes the issue."""
        return self.page.locator(f'[data-testid="hitl-close-{issue_number}"]')
