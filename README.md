# CFP Committee Lab

Six AI models forecast the College Football Playoff rankings from a frozen set of pre-release evidence. The models cast top-25 ballots with short explanations. The dashboard shows the combined vote, each model's rankings, and what changed when the AP poll or previous CFP rankings were hidden.

[Read the forecast and download the results](https://sunaybhat.me/cfp-committee/). The downloadable skill and results JSON let you analyze the ballots without paid API calls.

## Explore the archived run

The [original roster](data/ballots/2026-11-24/weekly-panel/) and [Head-to-Head First roster](data/ballots/2026-11-24/weekly-panel-v2/) each include their aggregate rankings, individual ballots, prompt metadata, run costs, and file checksums. Download the [agent skill](dashboard/SKILL.md) and the full results JSON from the dashboard to explore both the forecast and the roster comparison in a chatbot.

## Six-model weekly dashboard

Run `python -m cfpllm.panel` with an authorized frozen packet and `OPENROUTER_API_KEY`. The default `weekly-v3` profile uses only the mixed committee, with 14 seats across four poll settings and two voting rounds for 112 requested ballots. The 14th seat is Brand Bias. The two Head-to-Head First seats remain. The archived `weekly-v1` and `weekly-v2` profiles preserve the earlier 416-ballot matrix.

Build the static dashboard with `python dashboard/build.py --packet <packet.json> --run <weekly-panel-dir> --output <directory>`. Add `--lock <verification.json>` after verifying the timestamp proof, `--official <official.json>` once the matching official release is available, and `--unlisted` for a noindex page. Open the generated `index.html` alongside its assets. The download bundle contains derived results and the agent skill. Keep the source packet local under [CFBD's terms](https://collegefootballdata.com/terms).

To compare both roster versions for a release, run `python dashboard/compare_rosters.py` with the verified source packet and both run directories present. It matches ballots by model, committee, condition, and seat, then writes `roster-comparison.json` for the dashboard. For a new experiment, set a future release in `config.yaml`, fetch and lint the authorized packet, and use the weekly runner before the deadline. An independent input download can differ from an archived one.

## Run a new weekly forecast

Set the release, game cutoff, evidence cutoff, verified AP week, and AP/CFP publication dates in the YAML configuration. The game cutoff determines which scores count. The evidence cutoff can be the following Sunday or Monday so the packet includes the AP poll published after those games. Run an audited re-creation of a locked release from a separate working directory. Keep the keys in your environment.

```bash
git clone --single-branch --branch cfp-committee-lab https://github.com/SunayBhat1/sunaybhat1.github.io.git cfp-committee-lab
cd cfp-committee-lab
python -m venv .venv
.venv/bin/pip install -e '.[test]'
.venv/bin/cfpllm fetch
.venv/bin/cfpllm lint
.venv/bin/python -m cfpllm.panel --profile weekly-v3
```

The archived November 24 forecasts use a 4:00 PM ET cutoff ahead of the 7:30 PM ET rankings release. This repository's `lock/2026-11-24-v2-dfeed91d` tag records the released source and results snapshot. The run manifest records the original runner commit and frozen source fingerprint.

New packets include overall and FBS records, opponent record and scoring context, separately dated AP and CFP ranks, and available pregame opening spreads. The poll switches omit that poll's rankings everywhere in the prompt, including opponent context. Kickoff ranks require a verified dated poll from before the game and appear only where coverage is available.

### Research comparisons

`python -m cfpllm.research_pilot --config <file> --research <notes.json>` runs the same mixed committee with a packet-only vote and two dated research supplements. The notes contain a source, URL, publication date, and a short factual summary for each entry. Use the statistical set for game flow, efficiency, schedule strength, and strength of record. Use the pundit set for independent pre-release rankings and bracket projections with differing views. Keep actual target rankings and post-release material out of both. The pilot records its supplied search notes and role-specific instructions. Its model calls have no autonomous browser tools.

## Setup

Keep your API keys in environment variables. The weekly panel's model list and budget controls live in `src/cfpllm/panel.py`. The model calls use OpenAI-compatible chat completions with a system prompt and frozen user packet. The ballots have no access to browsing, tools, or retrieval.

`config.yaml` is the reusable release switch. For Dec. 1 set `games_through: 2026-11-28`, `prior_cfp_release: 2026-11-24`, and `release_id: 2026-12-01`. For Selection Day use `release_id: 2026-12-06`, set the prior release to Dec. 1, and confirm the championship Saturday date with the schedule before setting `games_through`.

## Single-model and scoring commands

The original single-model workflow is also available. Set `model` in `config.yaml` or use the `CFPLLM_MODEL` or `OPENAI_MODEL` environment variable for that workflow.

| Command | Purpose |
|---|---|
| `cfpllm fetch` | GET only CFBD endpoints and freeze `data/packets/<release>/packet.json` plus its SHA-256 sidecar. |
| `cfpllm lint [packet]` | Fail closed on cutoff, ranking leakage, shape, and integrity errors. |
| `cfpllm estimate` | Print the 312-call input/output-token and editable-price estimate without spending. |
| `cfpllm run` | Run/cache 2 mixes × 4 conditions × 3 temperatures × 13 agents. A run with fewer than 10 valid ballots aborts. |
| `cfpllm lock` | Build the manifest, commit/tag/push artifacts, and try to open the PR. |
| `cfpllm score --official data/official/YYYY-MM-DD.json` | Score every aggregate and baseline, then write the report. |
| `cfpllm report` | Re-render the Markdown report from an existing score file. |

The packet sidecar authenticates the full canonical file bytes: UTF-8, sorted keys, compact separators, no trailing newline. `meta.content_sha256` is an informational pre-embedding digest because a file cannot contain its own final SHA-256 value; `packet.sha256` is the authoritative full-file digest and is what lint verifies.

After the official release, add a 25-entry JSON file such as:

```json
{
  "release_id": "2026-11-24",
  "released_at": "2026-11-24T19:30:00-05:00",
  "rankings": [{"rank": 1, "team": "Georgia"}]
}
```

Use the packet's canonical CFBD names. A small explicit alias map handles common variants; unresolved names fail loudly. Unranked predictor teams receive rank 26 for the rank-error metrics.

## Verification

```bash
.venv/bin/python -m pytest
```

The tests run offline and cover packet hashing and lint leakage, ballot validation, Borda/tie breaks, and all five scoring metrics.
