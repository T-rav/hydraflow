# Rego unit tests for `hydraflow.adr_enforcement`, run by `make opa-test`.
#
# The Rego-native half of pilot #11750: each arm of the ladder and the
# fail-closed path is covered here directly, so a policy bug is localized
# before the Python-side parity test reports it as a whole-corpus divergence.
#
# `with input as ...` is only legal inside a rule BODY, so the input builder is
# a helper and every test does its own `with` — Rego has no fixture.
package hydraflow.adr_enforcement_test

import data.hydraflow.adr_enforcement

_obs(overrides) := object.union(
	{
		"enforcement_class": "REAL",
		"in_baseline_snapshot": false,
		"resolved": false,
		"exempt": false,
		"binds": "work",
	},
	overrides,
)

_input(overrides) := {
	"charter": {"standards": ["adr_enforcement"], "assurance": "internal"},
	"subjects": {"SUBJECT": _obs(overrides)},
}

_regulated_input(overrides) := {
	"charter": {"standards": ["adr_enforcement"], "assurance": "regulated-phi"},
	"subjects": {"SUBJECT": _obs(overrides)},
}

test_real_enforcement_is_compliant_and_not_blocking if {
	d := adr_enforcement.decisions.SUBJECT with input as _input({})
	d.status == "compliant"
	d.blocking == false
	d.remediation == "none"
}

test_weak_debt_with_no_lane_is_a_blocking_violation if {
	d := adr_enforcement.decisions.SUBJECT with input as _input({"enforcement_class": "WEAK"})
	d.status == "violated"
	d.blocking == true
	d.remediation == "file_issue"
}

test_missing_debt_with_no_lane_is_a_blocking_violation if {
	d := adr_enforcement.decisions.SUBJECT with input as _input({"enforcement_class": "MISSING"})
	d.status == "violated"
	d.blocking == true
}

test_baseline_debt_is_grandfathered_and_not_blocking if {
	d := adr_enforcement.decisions.SUBJECT with input as _input({"enforcement_class": "WEAK", "in_baseline_snapshot": true})
	d.status == "grandfathered"
	d.blocking == false
}

test_resolved_baseline_debt_that_is_still_weak_violates if {
	d := adr_enforcement.decisions.SUBJECT with input as _input({
		"enforcement_class": "WEAK",
		"in_baseline_snapshot": true,
		"resolved": true,
	})
	d.status == "violated"
	d.blocking == true
}

test_exempt_outranks_the_baseline_lane if {
	d := adr_enforcement.decisions.SUBJECT with input as _input({
		"enforcement_class": "WEAK",
		"in_baseline_snapshot": true,
		"exempt": true,
	})
	d.status == "exempt"
	d.blocking == false
}

test_a_real_adr_in_the_baseline_is_compliant_not_grandfathered if {
	# The ratchet's "grandfathered debt that is now REAL must be resolved"
	# rule, seen from the subject: the class outranks both lanes.
	d := adr_enforcement.decisions.SUBJECT with input as _input({"in_baseline_snapshot": true})
	d.status == "compliant"
}

test_a_subject_missing_a_required_fact_yields_no_decision if {
	result := adr_enforcement.decisions with input as {
		"charter": {"standards": ["adr_enforcement"]},
		"subjects": {"SUBJECT": {"enforcement_class": "WEAK", "exempt": false}},
	}
	count(result) == 0
}

test_a_subject_missing_a_required_fact_is_named_in_missing_facts if {
	msgs := adr_enforcement.missing_facts with input as {
		"charter": {"standards": ["adr_enforcement"]},
		"subjects": {"SUBJECT": {"enforcement_class": "WEAK", "exempt": false}},
	}
	count(msgs) == 1
}

test_one_thin_subject_withholds_every_decision if {
	# Fail closed across the whole batch: a partially-observed corpus must not
	# return the decisions it *could* make and let the caller read the gap as
	# compliance.
	result := adr_enforcement.decisions with input as {
		"charter": {"standards": ["adr_enforcement"]},
		"subjects": {
			"GOOD": _obs({}),
			"THIN": {"enforcement_class": "WEAK"},
		},
	}
	count(result) == 0
}

test_a_charter_that_does_not_name_the_standard_decides_nothing if {
	result := adr_enforcement.decisions with input as {
		"charter": {"standards": ["testing"], "assurance": "internal"},
		"subjects": {"SUBJECT": _obs({})},
	}
	count(result) == 0
}

test_an_empty_standards_list_governs_everything if {
	result := adr_enforcement.decisions with input as {
		"charter": {"standards": [], "assurance": "internal"},
		"subjects": {"SUBJECT": _obs({})},
	}
	count(result) == 1
}

# --- the composition probe (measurement 4) ---------------------------------

test_regulated_charter_blocks_grandfathered_weak_factory_binding_debt if {
	d := adr_enforcement.decisions.SUBJECT with input as _regulated_input({
		"enforcement_class": "WEAK",
		"in_baseline_snapshot": true,
		"binds": "factory",
	})
	d.status == "violated"
	d.blocking == true
}

test_binds_both_counts_as_binding_the_factory if {
	d := adr_enforcement.decisions.SUBJECT with input as _regulated_input({
		"enforcement_class": "WEAK",
		"in_baseline_snapshot": true,
		"binds": "both",
	})
	d.status == "violated"
}

test_an_internal_charter_still_grandfathers_the_same_debt if {
	# The probe must be the CHARTER's doing, not a new unconditional rule.
	d := adr_enforcement.decisions.SUBJECT with input as _input({
		"enforcement_class": "WEAK",
		"in_baseline_snapshot": true,
		"binds": "factory",
	})
	d.status == "grandfathered"
}

test_work_binding_debt_is_untouched_by_a_regulated_charter if {
	d := adr_enforcement.decisions.SUBJECT with input as _regulated_input({
		"enforcement_class": "WEAK",
		"in_baseline_snapshot": true,
		"binds": "work",
	})
	d.status == "grandfathered"
}

test_missing_class_debt_is_untouched_by_the_probe if {
	# The probe names WEAK specifically: a MISSING decision-of-record has no
	# enforcement to weaken, so the ratchet's carry still applies.
	d := adr_enforcement.decisions.SUBJECT with input as _regulated_input({
		"enforcement_class": "MISSING",
		"in_baseline_snapshot": true,
		"binds": "factory",
	})
	d.status == "grandfathered"
}

test_an_exemption_still_outranks_the_probe if {
	d := adr_enforcement.decisions.SUBJECT with input as _regulated_input({
		"enforcement_class": "WEAK",
		"in_baseline_snapshot": true,
		"exempt": true,
		"binds": "factory",
	})
	d.status == "exempt"
}
