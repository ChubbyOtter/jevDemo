# mobile-runner

AI-native Android/iOS UI test runner. Tests are plain natural-language steps; the
a11y tree drives grounding/actions, and [TypeSafe](https://typesafe.ai) (the `Jev`
model) answers the two judgments that actually need AI - "which element is that?"
and "is this assertion true?" - instead of running a full LLM on every step.

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
- **Android and iOS share everything except the a11y tree and gesture commands.**
  `mobile_runner/platforms/` holds the one piece that's genuinely different per
  platform (driver + element parsing); the compile cache, Jev calls, and run loop
  are identical code for both (see `mobile_runner/platforms/base.py`).
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

[Appium](https://appium.io) itself is shared by both platforms - one running server
handles Android and iOS sessions alike (needs Node >=20.19/22.12/24):

```bash
npm install -g appium
appium   # leave running in its own terminal
```

**Android** additionally needs, on the machine running the tests:

- `adb` on PATH (Android SDK platform-tools), with a device connected and authorized
  (`adb devices` shows `device`, not `unauthorized`)
- The `uiautomator2` driver: `appium driver install uiautomator2`
- Java (the uiautomator2 driver needs it)

**iOS** additionally needs:

- Xcode, with at least one Simulator runtime installed
- The `xcuitest` driver: `appium driver install xcuitest`
- A booted simulator (`xcrun simctl boot <udid>` - `xcrun simctl list devices` for udids),
  **or** a real device with WebDriverAgent code-signed (see below)

Both the Simulator and a real device are supported. A real device additionally needs
WebDriverAgent (WDA) - Appium's own automation helper app - signed with your own
identity, which a **free** Apple ID's Xcode "Personal Team" is sufficient for (no
paid Apple Developer Program needed). One-time setup:

1. In Xcode, open the WDA project Appium installed (typically
   `~/.appium/node_modules/appium-xcuitest-driver/node_modules/appium-webdriveragent/WebDriverAgent.xcodeproj`).
2. On both the `WebDriverAgentLib` and `WebDriverAgentRunner` targets' Signing &
   Capabilities tab: set Team to your Personal Team, and give each a unique bundle id
   (the shipped defaults, `com.facebook.*`, belong to Meta's team, not yours).
3. Build once for your connected, Developer-Mode-enabled device (Product → Test, ⌘U)
   to confirm it builds, installs, and launches - and to trust the signing certificate
   on-device (Settings → General → VPN & Device Management, once).
4. Set `IOS_XCODE_ORG_ID` (your Apple Developer Team ID) and `IOS_WDA_BUNDLE_ID` (the
   bundle id you gave `WebDriverAgentRunner`) in `.env` - see `.env.example`. With
   these set, Appium rebuilds/re-signs WDA itself on every session start, so step 3
   only has to happen once (this also transparently handles the free tier's 7-day
   provisioning-profile expiry).

The app under test needs none of this - a normal App-Store-installed app is
driven by its bundle id with no special build, since WDA's signing is entirely
separate from the app-under-test's signing.

## Running tests

```bash
python -m mobile_runner.cli tests/cases/home_google_search.txt              # one file, Android (default)
python -m mobile_runner.cli tests/cases/ios_settings_general.txt --platform ios
python -m mobile_runner.cli tests/cases/ --platform android                 # a suite - every *.txt in the dir
```

Each test case gets a clean starting state - a prior test case failing must never
corrupt the next one's result - but *how* differs per platform (each driver's
`reset_for_isolation`, see `platforms/base.py`):

- **Android**: the runner presses Home before every file in a suite, and
  `launch_app` force-restarts its app (`terminate_app` then `activate_app`) rather
  than resuming wherever it was left. A fresh Android process lands on the
  launcher activity, so Home alone is a safe reset between files.
- **iOS**: `reset_for_isolation` is deliberately a no-op. Confirmed live: pressing
  Home backgrounds whatever's in the foreground, and iOS writes that screen's
  UIKit state-restoration snapshot at that exact moment - a later hard kill can't
  un-write it, so backgrounding-then-relaunching resumed on the *previous* test's
  last screen instead of the app's root. iOS isolation instead relies entirely on
  `launch_app`, which uses `xcrun simctl terminate`/`launch` (an OS-level kill that
  doesn't trigger a state save) rather than Appium's `terminate_app`/`activate_app`
  (which goes through the same springboard-mediated path Home does, and doesn't
  reliably reset state either). A test case that doesn't start with `launch_app`
  has no isolation guarantee on iOS.

Each line in a test file is one natural-language step; blank lines and `#`
comments are ignored.

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
`swipe_up`, `swipe_down`, `wait` - fixed device actions, no grounding.
`back` - Android only; iOS has no hardware/software back button equivalent, and
`IOSDriver.back()` raises rather than guessing - target the screen's actual back
control with a `tap` step instead.
`launch_app` - deterministic: resolves the step's app name via `apps.json`, force-
restarts it. Add new apps to `apps.json` as `{"friendly name": {"android": "pkg.id",
"ios": "bundle.id"}}` (either key can be omitted if the app doesn't exist on that
platform).

## App registry

`mobile_runner/apps.json` maps a friendly app name (as a test step names it) to its
per-platform app id (Android package id / iOS bundle id). It's gitignored (your own
device's apps aren't necessarily anyone else's) - copy the template to get started:

```bash
cp mobile_runner/apps.example.json mobile_runner/apps.json
```

A step compiled with `verb: "launch_app"` and `literal_param` set to a name not in
the registry raises a clear error telling you to add it - never a guess.

## Layout

```
mobile_runner/
  models.py             CompiledStep, Element (platform-neutral)
  bounds.py             shared bounds-string helpers (both platforms format into this)
  platforms/
    base.py               MobileDriver protocol + Platform bundle
    android.py             AndroidDriver (UiAutomator2) + parse_elements/parse_screen_text
    ios.py                 IOSDriver (XCUITest) + parse_elements/parse_screen_text
  apps.json / apps.py   friendly app name -> {platform: app id} registry
  compiler.py           NL step -> CompiledStep (live Anthropic call, cached)
  precompile.py         offline counterpart to compiler.py
  cache.py              on-disk compile cache
  typesafe_client.py    Jev grounding + assertion calls (batched per screen)
  runner.py             orchestrates: compile -> ground/act or assert, per step
  cli.py                entry point; single file or a tests/cases/-style suite
tests/
  cases/                one *.txt per test case - this is what scales as more are added
  fixtures/             real a11y dumps pulled from a device, for offline testing
```

## Known limitations (MVP scope)

- No parallelism - a suite runs its test files sequentially on one device session.
- Each platform's element filter (and Android's bounds-containment label fallback)
  was tuned against real screens (the Android launcher, a real third-party app that
  under-reports accessibility flags, and iOS's Settings app); a new app may expose
  yet another shape this doesn't handle - treat grounding failures as a signal to
  inspect the real a11y dump, not assume the step's wording is wrong.
- Assertion checks retry once after `ASSERTION_RETRY_DELAY_SECONDS` on a FAIL, to
  absorb async content that renders after `is_loading` already reads false (no
  spinner, just a page that fills in over multiple frames) - confirmed live on a
  membership/plan page. A genuinely-false assertion just costs one extra Jev call
  before failing.
- iOS real-device suite isolation is weaker than the Simulator's. `simctl` (the
  Simulator's OS-level terminate/launch, which bypasses iOS's UIKit
  state-restoration snapshot entirely) has no real-device equivalent, so
  `IOSDriver.launch_app` falls back to Appium's WDA-mediated `terminate_app`/
  `activate_app` there - confirmed live (2 consecutive clean runs against a real
  device, testing a third-party app) that this is enough for apps that don't
  implement state restoration, but a third-party app that does could still resume
  mid-navigation instead of at its root, with no fix in place yet for that case.
