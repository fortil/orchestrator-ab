# orchestrator-ab

An A/B harness that measures which Claude model, at which effort level, deserves
the orchestrator seat of a coding-agent pipeline.

In a multi-agent pipeline, the orchestrator is the session that routes work
between specialized subagents: it parses the request, launches the plan,
critique, implement and review roles, and stays quiet. Which model sits in that
seat is usually inherited by accident, whatever the session opened with. This
harness puts each candidate model+effort in the seat on purpose, runs the same
small project through the pipeline, and grades what actually happened.

Built against my own multi-agent pipeline (tasky), discussed on my content
channels. The pipeline part is swappable; see
[Adapting it](#adapting-it-to-your-pipeline).

## What it grades

For every run (one fresh seed repo per run):

- **finish**: did the run emit its finish line (`COMPLETED` / `FAILED`), end in
  a `DECISION` stop, or die without a line
- **bypass**: did the orchestrator finish without launching the pipeline
  (implemented the work itself), judged from the run documents and the finish
  line
- **unbacked errors**: `ERROR:` lines emitted with no tool call nearby, the
  "blame the environment without looking" failure mode
- **decision discipline**: how many `DECISION:` stops, and whether each was
  backed by an executed command
- **contract silence**: text blocks outside the run's three output cases
  (progress narration the pipeline forbids)
- **orchestrator load**: tool calls by the session model, and writes outside
  the run's own documents (the orchestrator implementing code is a role
  violation)
- **seat cost**: context peak, and input / cache-read / cache-write / output
  tokens for the session model

## Arms

| Arm | Session model | Effort |
|---|---|---|
| `sonnet-medium` | claude-sonnet-5-5 | medium |
| `sonnet-low` | claude-sonnet-5-5 | low |
| `haiku-medium` | claude-haiku-5-5 | medium |
| `haiku-high` | claude-haiku-5-5 | high |
| `opus-low` | claude-opus-5-5 | low |
| `opus-medium` | claude-opus-5-5 | medium |

The subagents are launched per role with explicit model and effort by the
pipeline's own router, so the only variable between arms is the model and
effort of the orchestrating session.

## Stages

| Stage | What | Mode | Reps | Runs |
|---|---|---|---|---|
| 0 | smoke: preflight and finish line | xs | 1 per arm | headless |
| 1 | decision gate: a foreign staged file forces a human-decision stop | xs | 1 per arm | interactive |
| 2 | full pipeline: plan, critique, implement, review | m | 3 per arm | headless |
| 3 | pressure: long run | l | 3 per arm | headless |

## Results from the example run (November 2026, 18 runs)


| Arm | Full pipeline | Partial | Bypass | Seat cache read (range) |
|---|---|---|---|---|
| `opus-low` | **3/3** | 0 | 0 | 2.4-3.5M tok |
| `opus-medium` | **3/3** | 0 | 0 | 2.9-4.0M tok |
| `haiku-high` | 3/3 | 0 | 0 | 7.9-9.7M tok |
| `sonnet-medium` | 2/3 | 0 | 1 (confessed) | 2.4-3.1M tok |
| `haiku-medium` | 1/3 | 0 | 2 | 1.0-5.1M tok |
| `sonnet-low` | 1/3 | 1 (no commit) | 1 (no finish line) | 0.6-3.5M tok |

Findings:

- **Effort decides discipline more than the model.** At high effort the
  orchestrator ran the full pipeline every time. At medium, two thirds. At low,
  one third, and the cheapest arm sometimes skipped the pipeline without
  emitting its finish line.
- **The best orchestrator measured was Opus at low effort**: every valid run
  completed the full pipeline, silent and clean, at roughly a third of the seat
  tokens of the only other fully disciplined arm (Haiku at high). In API
  dollars that flips: Haiku's cache reads bill at $0.05/MTok versus Opus's
  $0.20, so Haiku high's seat came out about three times cheaper per run
  despite the triple token count.
- **When models bypass the pipeline, they do it differently.** Haiku kept
  branch and commit discipline while bypassing; Sonnet once left uncommitted
  changes on the default branch and once skipped the finish line entirely.
- **The code came out fine in all runs.** What bypassing costs is the
  independent critique and review, which is exactly what the pipeline exists to
  buy.

Raw per-run records are in `results/` with machine paths stripped.

## Usage

```bash
python3 arnes.py brazos                                   # list the arms
python3 arnes.py correr --etapa 0 --brazo sonnet-low      # prepare + run + extract one run
python3 arnes.py preparar --etapa 1 --brazo haiku-high    # stage 1 prints the interactive steps
python3 arnes.py extraer --todos                          # transcripts -> resultados/*.json
python3 arnes.py resumen                                  # summary table

# full stage in one batch (resumable; finished runs are skipped):
nohup caffeinate -is python3 -u arnes.py correr --etapa 2 --todos > runs/campana-e2.log 2>&1 &
```

Each run lives in `runs/<stage>-<arm>-r<rep>/` with a fresh clone of the seed
repo, its metadata, the CLI stdout and the debug log. Transcripts are read from
`~/.claude/projects/<encoded-run-path>/`; the extractor picks the orchestrator
transcript (it opens with the slash command) and ignores subagent sessions.

## Adapting it to your pipeline

The harness invokes a slash command (`/tasky <brief>` with fixed flags) on a
pipeline whose output contract is three cases: `ERROR:`, `DECISION:` and one
finish line. To point it at your own pipeline:

1. Edit `prompt_for()` in `arnes.py` to invoke your command.
2. Adjust the contract markers in `extraer_run()`: the finish-line regex, and
   the `DECISION:` / `ERROR:` prefixes.
3. Review `DOC_RE`, the allowlist of files the orchestrator is allowed to write
   (run documents); anything else its session writes is flagged as a suspected
   role violation.
4. Replace `seed/` with any small project and `briefs/` with your tasks.

The arms table (`ARMS`) is the only place that defines what gets compared:
add a line per model+effort you want to test.

## Method notes and caveats

- Context per call = `input_tokens + cache_read + cache_creation`. Sums cover
  the session model only; subagent work is identical between arms by design
  and is not counted.
- Three reps per arm, one small task. That is enough to see bypass behavior
  and seat cost; it is not enough to claim anything about long or hard tasks
  (stage 3 exists for that).
- Raw token counts are not dollars. Cache reads bill at different rates per
  model family.
- Weekly usage limits can kill a run mid-batch. One of the example runs died
  12 seconds in; the batch is resumable, finished runs are skipped, and that
  run was re-executed after the limit reset.
- The `debug.log` of each run carries permission rules with credentials. It
  stays inside the gitignored `runs/` directory and must never be committed or
  pasted.

## Files

```
arnes.py         the harness: prepare / run / extract / summarize
seed/            the 50-line Python CLI every run is launched on
briefs/          the four task briefs, one per stage
runs/            per-run state (gitignored)
resultados/      extracted metrics per run (gitignored)
results/         sanitized example records published with this repo
```

## License

[MIT](LICENSE)
