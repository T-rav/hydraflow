"""HITL items — human-in-the-loop corrections, surfaced at the top of Outcomes."""

from __future__ import annotations

from .base import BasePage


class HitlPage(BasePage):
    async def open(self) -> None:
        """Navigate to the dashboard's Outcomes tab, where HITL items render.

        HITL was merged into the Outcomes tab (#10482) — there is no
        standalone "HITL" tab to click anymore. ``_initialTabFromUrl``
        resolves ``?tab=outcomes`` directly (and still redirects a legacy
        ``?tab=hitl`` deep link there too), so deep-link straight to it
        instead of clicking a tab button by text.
        """
        await self.goto("/?tab=outcomes")

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
