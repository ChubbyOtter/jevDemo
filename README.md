# android-runner

AI-native Android UI test runner. Tests are plain natural-language steps; the a11y
tree drives grounding/actions, and [TypeSafe](https://typesafe.ai) (the `Jev` model)
answers the two judgments that actually need AI - "which element is that?" and
"is this assertion true?" - instead of running a full LLM on every step.

## Why this design

- **Actions are deterministic once grounded.** Appium/UiAutomator2 dumps the a11y
  tree; code filters it down to interactive elements (`elements.py`). Jev's `Choice`
  primitive then *selects* the matching element from that real candidate list - it
  never invents one, and always has a `none_of_these` escape hatch so a bad match
  fails the step instead of mistapping something.
- **Assertions are a single `Noul` call** - a probability, not generated text. They
  run against a separate, richer "all visible text" view (`parse_screen_text`), not
  just the interactive candidate list grounding uses - a real page can carry its
  meaning entirely in non-interactive labels (e.g. a membership plan's price).
- **Known operations stay in code, not Jev.** Launching an app by name
  (`apps.json` registry + `launch_app`) is a deterministic lookup - it never asks
  Jev anything.
- **Jev can't extract free text** (a literal like `"hunter2"` to type, or which app
  a friendly name maps to). That happens once per unique step, in a separate "compile"
  pass, cached by a hash of the step text (`cache.py`, `compiler.py`) - reruns of an
  unchanged test file make zero LLM calls for compiling. The compile pass can be
  done live via the Anthropic API, or offline by a coding agent writing straight
  into the cache (`precompile.py`) - see below.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env   # fill in TYPESAFE_API_KEY (required)
```

Device automation needs, on the machine running the tests:

- `adb` on PATH (Android SDK platform-tools), with a device connected and authorized
  (`adb devices` shows `device`, not `unauthorized`)
- [Appium](https://appium.io) with the `uiautomator2` driver (needs Node
  >=20.19/22.12/24):
  ```bash
  npm install -g appium
  appium driver install uiautomator2
  appium   # leave running in its own terminal
  ```
- Java (the uiautomator2 driver needs it)

## Running tests

```bash
python -m android_runner.cli tests/cases/home_google_search.txt   # one file
python -m android_runner.cli tests/cases/                   # a suite - every *.txt in the dir
```

Each test case gets a clean starting state: the runner presses Home before every
file in a suite, and `launch_app` force-restarts its app (`terminate_app` then
`activate_app`) rather than resuming wherever it was left - a prior test case
failing must never corrupt the next one's result. Each line in a test file is one
natural-language step; blank lines and `#` comments are ignored.

A suite shares one Appium session, one TypeSafe client, and one compile cache
across all its test files (session/client startup cost is paid once; every case
benefits from every other case's already-compiled steps).

## The compile step

`TYPESAFE_API_KEY` is required for every run (grounding + assertions). Compiling a
step into `{kind, verb, literal_param, target_description, assertion_text}` needs an
LLM too, but only once per unique step text, and it doesn't have to be a live API
call:

- **Live**: set `ANTHROPIC_API_KEY`; `StepCompiler` calls Claude on any cache miss.
- **Offline**: have a coding agent read the test file, reason out each step's record
  per the field semantics in `compiler.py`'s `SYSTEM_PROMPT`, and write them with
  `precompile.precompile(cache_path, [CompiledStep(...), ...])`. `StepCompiler` then
  treats them as ordinary cache hits and never touches the Anthropic API.

The cache lives at `.cache/compiled_steps.json` by default (`--cache-file` to
override).

## Verbs

`tap`, `type`, `scroll_to` - grounded via Jev against the current screen; auto-retry
by scrolling up to `MAX_SCROLL_ATTEMPTS` times if the target isn't visible yet, and
give up only once scrolling stops changing the screen (reached the end of a list).
`swipe_up`, `swipe_down`, `back`, `wait` - fixed device actions, no grounding.
`launch_app` - deterministic: resolves the step's app name via `apps.json`, force-
restarts it. Add new apps to `apps.json` as `{"friendly name": "package.id"}`.

## App registry

`android_runner/apps.json` maps a friendly app name (as a test step names it) to its
package id. It's gitignored (your own device's apps aren't necessarily anyone else's)
- copy the template to get started:

```bash
cp android_runner/apps.example.json android_runner/apps.json
```

A step compiled with `verb: "launch_app"` and `literal_param` set to a name not in
the registry raises a clear error telling you to add it - never a guess.

## Layout

```
android_runner/
  models.py           CompiledStep, Element
  elements.py          a11y XML -> filtered/deduped candidate elements (parse_elements),
                        and -> all visible text for assertions (parse_screen_text)
  apps.json / apps.py   friendly app name -> package id registry
  compiler.py          NL step -> CompiledStep (live Anthropic call, cached)
  precompile.py         offline counterpart to compiler.py
  cache.py              on-disk compile cache
  typesafe_client.py    Jev grounding + assertion calls (batched per screen)
  driver.py             Appium session wrapper: dump, tap, type, swipe, launch, home
  runner.py             orchestrates: compile -> ground/act or assert, per step
  cli.py                entry point; single file or a tests/cases/-style suite
tests/
  cases/                one *.txt per test case - this is what scales as more are added
  fixtures/             real a11y dumps pulled from a device, for offline testing
```

## Known limitations (MVP scope)

- No parallelism - a suite runs its test files sequentially on one device session.
- `elements.py`'s element filter and bounds-containment label fallback were tuned
  against real screens (the Android launcher, and a real third-party app that
  under-reports accessibility flags); a new app may expose yet another shape this
  doesn't handle - treat grounding failures as a signal to inspect the real a11y
  dump, not assume the step's wording is wrong.
- Assertion checks retry once after `ASSERTION_RETRY_DELAY_SECONDS` on a FAIL, to
  absorb async content that renders after `is_loading` already reads false (no
  spinner, just a page that fills in over multiple frames) - confirmed live on a
  membership/plan page. A genuinely-false assertion just costs one extra Jev call
  before failing.
- iOS is a planned follow-up, not started.
