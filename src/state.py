"""State persistence for HydraFlow — backed by Dolt."""

from dolt.store import DoltStore as StateTracker

__all__ = ["StateTracker"]
