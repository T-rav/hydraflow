# METADATA
# title: ADR enforcement debt — the ratchet's rules, as policy
# description: |
#   The OPA half of pilot #11750. Decides the `adr_enforcement` standard from
#   the SAME normalized facts `policy.facts.collect_adr_enforcement_facts`
#   emits, and must reach the SAME verdict as `policy.python_engine`.
#
#   Input document (built by `policy.opa_engine`, never read from disk here):
#
#     {"charter":  {"standards": ["adr_enforcement"], "assurance": "internal"},
#      "subjects": {"ADR-0091": {"enforcement_class": "MISSING",
#                                "in_baseline_snapshot": true,
#                                "resolved": false,
#                                "exempt": false,
#                                "binds": "factory"}}}
#
#   Everything below is pure: no `http.send`, no `opa.runtime`, no data
#   documents loaded from anywhere but this file. #11687's rule is that a
#   conformance verdict is reproducible offline from a clean checkout, and an
#   engine that could reach the network at decision time would break it.
package hydraflow.adr_enforcement

# ---------------------------------------------------------------------------
# PARITY SECTION — everything `policy.python_engine._decide_enforcement` does.
# The cross-standard rule the pilot is really measuring is in the PROBE SECTION
# at the bottom; the two are kept apart so each can be line-counted on its own.
# ---------------------------------------------------------------------------

# WEAK + MISSING are the unenforced-decision debt (adr_conformance.EnforcementClass).
debt_classes := {"WEAK", "MISSING"}

# Fail closed on thin evidence, exactly as `_indexed` does: a subject missing
# any fact its standard needs is an error, never a default. Rego's native
# behaviour is the opposite — an absent key makes a rule body simply not fire,
# which would silently downgrade a violation to "no decision" — so the check
# has to be written out.
required_facts := {"enforcement_class", "in_baseline_snapshot", "resolved", "exempt", "binds"}

missing_facts contains msg if {
	some subject, obs in input.subjects
	absent := required_facts - object.keys(obs)
	count(absent) > 0
	msg := sprintf("%s: missing required fact(s) %v", [subject, sort(absent)])
}

# An empty `standards` list governs everything (`Charter.governs` fails OPEN
# there and only there: no charter written yet is not "nothing is enforced").
governed if count(object.get(input, ["charter", "standards"], [])) == 0

governed if "adr_enforcement" in input.charter.standards

in_debt(obs) if obs.enforcement_class in debt_classes

# The ladder. Order is the whole rule: exempt outranks the baseline, and the
# class outranks both.
status(obs) := "compliant" if not in_debt(obs)

else := "exempt" if obs.exempt

else := "violated" if probe_blocks(obs)

else := "grandfathered" if {
	obs.in_baseline_snapshot
	not obs.resolved
}

else := "violated"

reason(obs) := sprintf("enforcement classifies %s — bound to a real asserting check", [obs.enforcement_class]) if {
	status(obs) == "compliant"
}

else := sprintf("%s but allow-listed as process-only in docs/standards/adr_enforcement/exemptions.md", [obs.enforcement_class]) if {
	status(obs) == "exempt"
}

else := sprintf("%s but carried by the frozen enforcement-debt baseline; shrink-only — pay it down by giving the ADR a real check", [obs.enforcement_class]) if {
	status(obs) == "grandfathered"
}

else := probe_reason(obs) if probe_blocks(obs)

else := sprintf("%s enforcement debt that is neither grandfathered nor exempt", [obs.enforcement_class])

# A violation is the only status that stops a merge; a ratchet-carried debt is
# still a debt, which is why `blocking` is a field and not a synonym of status.
decisions[subject] := d if {
	governed
	count(missing_facts) == 0
	some subject, obs in input.subjects
	verdict := status(obs)
	d := {
		"standard": "adr_enforcement",
		"subject": subject,
		"status": verdict,
		"blocking": verdict == "violated",
		"reason": reason(obs),
		"remediation": remediation(verdict),
	}
}

remediation(verdict) := "file_issue" if verdict == "violated"

else := "none"

# ---------------------------------------------------------------------------
# PROBE SECTION (measurement 4) — the cross-standard rule.
#
#   An ADR that binds the FACTORY and is only weakly enforced is blocking even
#   when the ratchet grandfathers it, once the repo's charter declares a
#   regulated assurance class.
#
# Cross-standard because it joins a fact about the SUBJECT (`binds`, ADR-0123)
# to a fact about the REPO (`articles.assurance`, ADR-0143) — the shape that
# has no home in a per-subject ladder. `both` counts with `factory`: ADR-0123
# defines `both` as binding work AND factory.
#
# The assurance vocabulary is `internal` | `regulated-<name>`, open on the
# right, so this matches the prefix rather than an enumeration that would
# silently stop covering the next regulated class.
# ---------------------------------------------------------------------------

regulated if startswith(object.get(input, ["charter", "assurance"], "internal"), "regulated-")

probe_blocks(obs) if {
	regulated
	obs.binds in {"factory", "both"}
	obs.enforcement_class == "WEAK"
}

probe_reason(obs) := sprintf("WEAK enforcement on a Binds:%s decision under a regulated charter — the ratchet does not carry factory-binding debt in a regulated repo", [obs.binds])
