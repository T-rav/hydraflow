from auto_tighten.models import FileEdit
from auto_tighten.ratchet_adapter import RatchetAdapter


class _FakeAdapter:
    ratchet_id = "fake"

    def current(self, repo_root):
        return 80.0

    def baseline(self, repo_root):
        return 70.0

    def is_tighter(self, a, b):
        return a > b

    def weakest(self, a, b):
        return min(a, b)

    def apply_margin(self, floor):
        return floor - 1.0

    def render_tightened(self, repo_root, value):
        return [FileEdit(path="x", new_text="y")]

    def dedup_key(self, value):
        return f"fake:{value}"


def test_fake_adapter_satisfies_protocol():
    assert isinstance(_FakeAdapter(), RatchetAdapter)
