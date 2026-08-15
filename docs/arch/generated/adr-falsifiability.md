# ADR Falsifiability Baseline

The **claim density** of each Accepted ADR — the fraction of its statements carrying a checkable marker (a normative keyword, code span, path, number, or named symbol). This is the *golden baseline* the spec-intake gate (#10830) calibrates against (#10821, ADR-0131): a prose critic has no natural zero, so the mush it flags on new specs is only trustworthy relative to what sound ADRs already score. Deterministic — a function of the ADR text alone.

## Baseline

- **Population:** Accepted (81 ADRs)
- **Mean claim density:** 53%
- **Mush floor:** 25% (density below this reads as mush)
- **Below the mush floor:** _(none — the sound corpus clears it)_

## Per-ADR claim density

| ADR | Density | Checkable | Statements |
|-----|--------:|----------:|-----------:|
| ADR-0083 | 27% | 12 | 45 |
| ADR-0035 | 28% | 23 | 83 |
| ADR-0024 | 30% | 33 | 110 |
| ADR-0019 | 31% | 29 | 95 |
| ADR-0113 | 31% | 38 | 123 |
| ADR-0008 | 33% | 22 | 67 |
| ADR-0023 | 33% | 31 | 93 |
| ADR-0025 | 37% | 16 | 43 |
| ADR-0018 | 38% | 49 | 130 |
| ADR-0016 | 38% | 33 | 86 |
| ADR-0005 | 39% | 14 | 36 |
| ADR-0034 | 41% | 45 | 110 |
| ADR-0015 | 41% | 51 | 124 |
| ADR-0001 | 41% | 14 | 34 |
| ADR-0041 | 42% | 42 | 101 |
| ADR-0111 | 42% | 55 | 131 |
| ADR-0017 | 42% | 36 | 85 |
| ADR-0114 | 43% | 39 | 91 |
| ADR-0027 | 43% | 66 | 152 |
| ADR-0087 | 44% | 76 | 174 |
| ADR-0104 | 45% | 29 | 65 |
| ADR-0012 | 45% | 70 | 156 |
| ADR-0117 | 46% | 38 | 82 |
| ADR-0011 | 47% | 47 | 101 |
| ADR-0014 | 47% | 44 | 94 |
| ADR-0115 | 48% | 86 | 181 |
| ADR-0002 | 48% | 62 | 130 |
| ADR-0007 | 48% | 35 | 73 |
| ADR-0112 | 48% | 44 | 91 |
| ADR-0058 | 49% | 45 | 92 |
| ADR-0107 | 49% | 87 | 177 |
| ADR-0037 | 49% | 37 | 75 |
| ADR-0042 | 51% | 49 | 97 |
| ADR-0109 | 51% | 41 | 80 |
| ADR-0050 | 52% | 67 | 130 |
| ADR-0096 | 52% | 33 | 63 |
| ADR-0004 | 53% | 31 | 59 |
| ADR-0102 | 53% | 39 | 74 |
| ADR-0053 | 53% | 38 | 72 |
| ADR-0118 | 53% | 19 | 36 |
| ADR-0051 | 53% | 28 | 53 |
| ADR-0098 | 53% | 55 | 104 |
| ADR-0088 | 53% | 27 | 51 |
| ADR-0089 | 53% | 26 | 49 |
| ADR-0119 | 54% | 27 | 50 |
| ADR-0061 | 54% | 26 | 48 |
| ADR-0047 | 54% | 44 | 81 |
| ADR-0009 | 56% | 59 | 106 |
| ADR-0094 | 56% | 58 | 104 |
| ADR-0032 | 56% | 33 | 59 |
| ADR-0057 | 57% | 27 | 47 |
| ADR-0116 | 58% | 111 | 192 |
| ADR-0021 | 59% | 140 | 239 |
| ADR-0097 | 60% | 55 | 92 |
| ADR-0056 | 60% | 57 | 95 |
| ADR-0090 | 60% | 27 | 45 |
| ADR-0022 | 60% | 91 | 151 |
| ADR-0043 | 60% | 38 | 63 |
| ADR-0110 | 60% | 58 | 96 |
| ADR-0099 | 61% | 59 | 97 |
| ADR-0049 | 61% | 39 | 64 |
| ADR-0045 | 61% | 72 | 118 |
| ADR-0052 | 64% | 43 | 67 |
| ADR-0010 | 64% | 65 | 101 |
| ADR-0060 | 65% | 39 | 60 |
| ADR-0134 | 66% | 127 | 193 |
| ADR-0065 | 66% | 29 | 44 |
| ADR-0092 | 68% | 27 | 40 |
| ADR-0095 | 68% | 48 | 71 |
| ADR-0064 | 69% | 81 | 118 |
| ADR-0103 | 70% | 73 | 104 |
| ADR-0054 | 71% | 44 | 62 |
| ADR-0093 | 71% | 66 | 93 |
| ADR-0100 | 72% | 58 | 81 |
| ADR-0062 | 72% | 41 | 57 |
| ADR-0071 | 72% | 18 | 25 |
| ADR-0085 | 72% | 18 | 25 |
| ADR-0106 | 73% | 27 | 37 |
| ADR-0029 | 76% | 29 | 38 |
| ADR-0030 | 77% | 30 | 39 |
| ADR-0028 | 83% | 29 | 35 |


<!-- arch:generated -->
