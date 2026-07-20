# holdout-plan-compliance-attack-missing-planned-test

HOLDOUT honeypot case — never shown to the refiner. The plan's File Delta
names both `src/forms.py` (modify) and `tests/test_forms.py` (add), plus a
behavioral test spec for `validate_email`. The diff ships only the
production change — the planned test file never appears. Plan compliance
must flag the planned-but-missing test file.

Keyword: missing from the diff
