"""Regression test for issue #6449.

ShapePhase._save_html_artifact (line 749-754) calls
``path.write_text(html, encoding="utf-8")`` with no try/except. If the
artifacts directory has permission issues or the disk is full, the
OSError propagates uncaught — crashing shape finalization and leaving
the issue stranded with no label transition.

The artifact is optional (a dashboard convenience). A write failure
should log a warning and allow finalization to continue.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch  # noqa: F401

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from shape_phase import ShapePhase  # noqa: E402


class TestIssue6449HtmlArtifactWriteFailure:
    """_save_html_artifact must not propagate OSError."""

    def _make_phase(self, data_root: Path) -> ShapePhase:
        """Create a minimal ShapePhase with only _config.data_root set."""
        phase = object.__new__(ShapePhase)
        phase._config = SimpleNamespace(data_root=data_root)
        return phase

    def test_permission_error_does_not_propagate(self, tmp_path: Path) -> None:
        """When the artifacts directory is not writable, _save_html_artifact
        must catch the OSError and not let it propagate.

        BUG: Currently the exception propagates uncaught because there is
        no try/except around path.write_text on line 754.
        """
        phase = self._make_phase(tmp_path)

        # Create the shape artifacts directory, then make it read-only
        artifacts_dir = tmp_path / "artifacts" / "shape"
        artifacts_dir.mkdir(parents=True)
        artifacts_dir.chmod(0o444)

        try:
            # This SHOULD silently log a warning and return.
            # BUG: It raises PermissionError instead.
            phase._save_html_artifact(42, "<html>test</html>")
        finally:
            # Restore permissions so pytest can clean up tmp_path
            artifacts_dir.chmod(0o755)

    def test_oserror_does_not_propagate(self, tmp_path: Path) -> None:
        """When write_text raises any OSError (e.g. disk full),
        _save_html_artifact must catch it and not propagate.

        BUG: No error handling exists — any OSError crashes the caller.
        """
        phase = self._make_phase(tmp_path)

        # Force write_text to raise an OSError simulating disk-full
        original_write_text = Path.write_text

        def _failing_write_text(self_path, *args, **kwargs):
            if isinstance(self_path, Path) and "issue-99" in self_path.name:
                raise OSError(28, "No space left on device")
            return original_write_text(self_path, *args, **kwargs)

        with patch.object(Path, "write_text", new=_failing_write_text):
            # This SHOULD silently log a warning and return.
            # BUG: The OSError propagates uncaught.
            phase._save_html_artifact(99, "<html>disk full</html>")
