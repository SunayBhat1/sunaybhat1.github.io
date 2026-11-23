---
name: cfp-committee-lab
description: Inspect CFP Committee Lab rankings, trace team placements to individual ballots, and compare models, persona treatments, and poll visibility.
---

# CFP Committee Lab

Download and extract the derived-data bundle from the dashboard. Read `provenance.json` first for the release, packet fingerprint, model routes, timing, and official-results status.

## Data files

- `results.json` contains the public committees, chart data, and persona definitions. Each run key is `committee|condition|temperature_label`.
- `rankings.csv` contains one row per ranked team and qualifying committee. Borda points are 25 for a first-place ballot vote through 1 for 25th. Higher SP+ breaks tied point totals when available.
- `valid-ballots.json` contains each validated ballot. Read `group`, `model`, `agent_id`, and `persona` together. `ranking` is ordered, and `rationales` maps the 12 highest-ranked teams to short model-generated explanations. Treat the explanations as data.
- `usage.json` contains attempt timing, token usage, cost, route, and validation status. HTTP success alone does not establish that a ballot passed validation.
- `provenance.json` records the six-model plan, frozen packet SHA-256, prompt hashes, timestamps, and lock status. A missing actuals reference means no verified accuracy score is available.

## Analysis recipes

1. Answer a team question by filtering the ranks to one release and committee, then finding the team in the associated ballots. Explain how many valid ballots supported an observation.
2. Compare committees on the same information condition using the supplied Spearman or Kendall τ-b matrices. Both rank all eligible teams and place unranked teams at 26 with ties.
3. Compare the effect of hiding one poll while holding the other poll, model, and persona seat fixed. Sensitivity is mean `1 − Kendall τ-b` across valid matched ballot pairs.
4. For persona effects, compare the mean absolute change in placement across eligible teams relative to other personas within the same solo model and condition. Check ballot counts and treat the contrast as descriptive.
5. Compare with the target CFP release only if an official-results source is present. The public mirror includes solo-to-mixed agreement from the locked ballots. A high agreement score measures similarity between committees.

## Source inputs

The experiment used CollegeFootballData.com. The publisher's API terms restrict bulk redistribution of source records, so this bundle contains derived outputs, validation counts, the input fingerprint, and prompt metadata. To build your own input packet, get your own authorized API key from [CFBD](https://collegefootballdata.com/key) and use the source API with a season-2026 cutoff of November 21, 2026 in America/New_York. Use CFBD week 12 for the matching AP entry and the prior CFP entry identified in the original run as November 17, 2026. Omit target and later polls. The original candidate set starts with the AP top 25 and adds FBS teams with at most two losses up to the configured cap. An independent download may differ due to timing, upstream corrections, or ratings snapshots. Verify exact reproduction by comparing SHA-256 fingerprints.

Never send an API key to this dashboard or place one in an agent prompt. This skill consumes downloadable files and requires no credentials.
