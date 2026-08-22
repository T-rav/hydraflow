"""Unit tests for the single-owner issue ownership registry (#11535)."""

from __future__ import annotations

import pytest

from driver_ownership import DriverOwnershipRegistry


def test_a_disabled_registry_reports_no_ownership_even_after_a_claim_attempt() -> None:
    registry = DriverOwnershipRegistry(enabled=False)
    registry.claim(1, driver_id="drv-1", epoch=0)

    assert registry.owns(1) is False


def test_a_disabled_registry_refuses_a_claim() -> None:
    registry = DriverOwnershipRegistry(enabled=False)

    assert registry.claim(1, driver_id="drv-1", epoch=0) is False


def test_a_disabled_registry_reports_no_owned_issues() -> None:
    registry = DriverOwnershipRegistry(enabled=False)
    registry.claim(1, driver_id="drv-1", epoch=0)

    assert registry.owned_issues == frozenset()


def test_an_enabled_registry_owns_an_issue_after_a_successful_claim() -> None:
    registry = DriverOwnershipRegistry(enabled=True)
    registry.claim(1, driver_id="drv-1", epoch=0)

    assert registry.owns(1) is True


def test_a_second_driver_claiming_an_already_held_issue_is_refused() -> None:
    registry = DriverOwnershipRegistry(enabled=True)
    registry.claim(1, driver_id="drv-1", epoch=0)

    assert registry.claim(1, driver_id="drv-2", epoch=0) is False


def test_a_refused_second_claim_leaves_the_original_holder_unchanged() -> None:
    registry = DriverOwnershipRegistry(enabled=True)
    registry.claim(1, driver_id="drv-1", epoch=0)
    registry.claim(1, driver_id="drv-2", epoch=0)

    # Only the original holder can still release at its own epoch.
    assert registry.release(1, driver_id="drv-1", epoch=0) is True


def test_the_same_driver_re_claiming_at_a_higher_epoch_succeeds() -> None:
    registry = DriverOwnershipRegistry(enabled=True)
    registry.claim(1, driver_id="drv-1", epoch=0)

    assert registry.claim(1, driver_id="drv-1", epoch=1) is True


@pytest.mark.parametrize(
    ("held_epoch", "releasing_driver", "releasing_epoch", "expected"),
    [
        # Only the current holder, at the epoch it holds, may let go.
        (0, "drv-1", 0, True),
        # A different driver cannot free someone else's claim.
        (0, "drv-2", 0, False),
        # A generation fenced out by recovery cannot free the new owner's claim.
        (1, "drv-1", 0, False),
    ],
)
def test_only_the_current_holder_at_its_own_epoch_may_release(
    held_epoch: int, releasing_driver: str, releasing_epoch: int, expected: bool
) -> None:
    registry = DriverOwnershipRegistry(enabled=True)
    registry.claim(1, driver_id="drv-1", epoch=held_epoch)

    released = registry.release(1, driver_id=releasing_driver, epoch=releasing_epoch)

    assert released is expected


def test_release_by_the_holder_at_the_correct_epoch_clears_ownership() -> None:
    registry = DriverOwnershipRegistry(enabled=True)
    registry.claim(1, driver_id="drv-1", epoch=0)
    registry.release(1, driver_id="drv-1", epoch=0)

    assert registry.owns(1) is False


def test_release_at_a_stale_epoch_leaves_ownership_intact() -> None:
    registry = DriverOwnershipRegistry(enabled=True)
    registry.claim(1, driver_id="drv-1", epoch=1)
    registry.release(1, driver_id="drv-1", epoch=0)

    assert registry.owns(1) is True


def test_release_all_clears_every_claim() -> None:
    registry = DriverOwnershipRegistry(enabled=True)
    registry.claim(1, driver_id="drv-1", epoch=0)
    registry.claim(2, driver_id="drv-2", epoch=0)
    registry.release_all()

    assert registry.owned_issues == frozenset()
