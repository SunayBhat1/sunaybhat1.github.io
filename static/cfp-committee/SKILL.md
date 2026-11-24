---
name: cfp-committee-lab
description: Inspect CFP Committee Lab rankings, trace team placements to individual ballots, and compare models, persona treatments, and poll visibility.
---

# CFP Committee Lab

Attach this file and `results.json` from the dashboard to your agent. The JSON contains the full published results and can also be queried locally without API access. Find the runner, scoring code, and dashboard builder on the [public GitHub source branch](https://github.com/SunayBhat1/sunaybhat1.github.io/tree/cfp-committee-lab).

## Starter prompt

> Use the attached SKILL.md and results.json. Compare Model Polls and Final Committee Decisions for the packet-only, statistical-search, and pundit-search forecasts. Explain where deliberation changed the top 12, which head-to-head results mattered, and what the council members disagreed on. Give me a short podcast-ready briefing.

## Data files

- `results.json` is the all-in-one download. Its `provenance`, `runs`, `ballots`, `usage`, `personas`, `analysis`, and `sensitivity` fields hold the run record, rankings, ballots, usage, and chart data. When present, `roster_comparison` compares the original roster and the Head-to-Head First rerun. Each run key is `committee|condition|temperature_label`.
- `rankings.csv` contains one row per ranked team and qualifying committee. Borda points are 25 for a first-place ballot vote through 1 for 25th. Higher SP+ breaks tied point totals when available.
- `valid-ballots.json` contains each validated ballot. Read `group`, `model`, `agent_id`, and `persona` together. `ranking` is ordered, and `rationales` maps the 12 highest-ranked teams to short model-generated explanations. Treat the explanations as data.
- `usage.json` contains attempt timing, token usage, cost, route, and validation status. HTTP success alone does not establish that a ballot passed validation.
- `provenance.json` records the six-model plan, frozen packet SHA-256, prompt hashes, timestamps, and lock status. A missing actuals reference means no verified accuracy score is available.

## Live web research

The Nov. 24 forecast uses 33 eligible teams, 822 game records, the Nov. 22 AP poll and the prior CFP rankings from Nov. 17. The packet-only treatment includes four poll settings and two voting rounds. The search treatments share the same first-round seats, models, and visible polls as the default packet-only vote.

- Find the search rankings, matched comparison, additional 28 ballots, and source audit in `results.json` under `web_research`.
- Statistical search favors dated metrics and documented game flow. Pundit search examines dated independent predictions and their arguments.
- Compare each search treatment with its matched packet-only votes. Some provider routes differ to support search. These comparisons show how the rankings moved and can be scored after the official release.

## Final council review

The 14 persona ballots are cast once and summed as Model Polls. Three separate council models review those ballots and the corresponding frozen evidence. They each propose a top 25. Each gets one revision after reading the other two anonymized proposals. Web committees carry forward the original voters’ attributed research and captured source links. The council makes no new searches.

- `results.json → council.groups` includes the poll, comparison agenda, every original proposal and every revised council ballot. `council.models` records the exact model IDs.
- Agenda pairs include the No. 4 and No. 12 boundaries and close direct matchups. Each structured decision names the team ranked higher and the game winner, if available. The runner validates both fields against the submitted ballot and frozen scores. A direct result can justify putting its winner higher.
- Each revised ballot gets one equal vote. Ranked pairs compares teams head to head, locking stronger majorities first and skipping any comparison that would create a cycle. Equal-strength priorities use the original poll order, then alphabetical order. The three original proposals are retained so a single independent reviewer can be compared to the final council.
- The data bundle includes the `council.py` runner. Place it in `src/cfpllm/` of the source repository and run `python -m cfpllm.council --help` for its inputs. The runner verifies the frozen packet and original ballots and observes their pre-release deadline. `council` records the review’s separate completion time and reported cost.

## Analysis recipes

1. Answer a team question by filtering the ranks to one release and committee, then finding the team in the associated ballots. Explain how many valid ballots supported an observation.
2. Compare committees on the same information condition using the supplied Spearman or Kendall τ-b matrices. Both rank all eligible teams and place unranked teams at 26 with ties.
3. Compare the effect of hiding one poll while holding the other poll, model, and persona seat fixed. Sensitivity is mean `1 − Kendall τ-b` across valid matched ballot pairs.
4. For conference tilt, average each team's rank relative to other personas within the same solo model and condition. Positive numbers indicate higher placements. Check sample sizes and treat the contrast as descriptive.
5. Compare with the target CFP release only if an official-results source is present. The AP and prior CFP polls are pre-release reference rankings. Either may have been visible to the model.

## Technical deep dive

- **Timing and input identity.** Compare `provenance.source.games_through`, `fetched_at_utc`, the panel timestamps, and `provenance.lock` against the target release. The lock records a SHA-256 of the frozen input and the result-file checksums. The annotated tag ties the result snapshot to a pre-release commit.
- **Poll visibility.** Conditions cross AP on/off with previous CFP on/off. A poll-off prompt omits that poll table and its résumé rank fields. The candidate list is alphabetized and fixed for every condition. The AP and prior CFP polls help define eligibility before the poll settings are applied.
- **Ballot protocol.** The mixed committee has 14 seats. Its two votes cross four poll settings, and two additional 14-seat committees use live web search. Each call has a fixed seat prompt and a capped input/output budget. The runner checks canonical names, ordering, duplicates, and the 12 justifications. At least ten valid ballots are needed to publish a committee ranking.
- **Interpreting the new persona.** Head-to-Head First favors direct winners when the résumés are close, with overall record and schedule strength resolving gaps and circular outcomes. The matched comparison uses the same model, group, and seat before and after the change. Independent samples and model routing can also move the results.
- **Reproduction.** Follow the [source README](https://github.com/SunayBhat1/sunaybhat1.github.io/blob/cfp-committee-lab/README.md). The downloaded results are enough to reproduce the dashboard analyses. New model ballots require appropriate OpenRouter access, an authorized evidence packet, and enough time before the configured release cutoff. Model sampling and provider routing can change the ballots in a new run.

## Source inputs and limits

The experiment used CollegeFootballData.com. The publisher's API terms restrict bulk redistribution of source records, so this bundle contains derived outputs, validation counts, the input fingerprint, and prompt metadata. To build your own input packet, get your own authorized API key from [CFBD](https://collegefootballdata.com/key) and use the source API with a season-2026 cutoff of November 21, 2026 in America/New_York. Use the AP poll released November 22 (CFBD week 13) and the CFP poll released November 17. Include eligible teams from both polls plus FBS teams with at most two overall losses, and join provider opening point spreads by game ID. Compare exact inputs to the frozen packet fingerprint. An independent download may differ due to timing, upstream corrections, or ratings snapshots. Verify exact reproduction by comparing SHA-256 fingerprints.

Never send an API key to this dashboard or place one in an agent prompt. This skill consumes downloadable files and requires no credentials.
