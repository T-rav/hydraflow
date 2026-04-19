"""HITL tab — human-in-the-loop items awaiting corrections."""

from __future__ import annotations

from .base import BasePage


class HitlPage(BasePage):
    async def open(self) -> None:
        await self.goto("/?tab=hitl")

    def item(self, issue_number: int):
        return self.page.locator(f'[data-testid="hitl-item-{issue_number}"]')

    def correction_input(self, issue_number: int):
        return self.page.locator(
            f'[data-testid="hitl-correction-input-{issue_number}"]'
        )

    def submit_button(self, issue_number: int):
        return self.page.locator(f'[data-testid="hitl-submit-{issue_number}"]')
