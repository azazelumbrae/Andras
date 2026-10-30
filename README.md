<p align="center">
  <img src="assets/hero.jpg" alt="ANDRAS, lord of discord" width="100%">
</p>

<h1 align="center">ANDRAS</h1>

<p align="center">
  <strong>A social engineering attacker that runs on your laptop.</strong><br>
  OSINT against one real human, evidence with provenance, an on-message pretext, and a
  multi-channel campaign that adapts when the target goes quiet.
</p>

<p align="center">
  <a href="https://github.com/azazelumbrae/Andras/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/azazelumbrae/Andras/actions/workflows/ci.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="License: GPL-3.0-or-later" src="https://img.shields.io/badge/license-GPL--3.0--or--later-blue.svg"></a>
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-3776ab.svg">
  <img alt="Local-first" src="https://img.shields.io/badge/local--first-2ea44f.svg">
  <img alt="Status: alpha" src="https://img.shields.io/badge/status-alpha-orange.svg">
</p>

<p align="center">
  <a href="#install">Install</a> ·
  <a href="#quickstart">Quickstart</a> ·
  <a href="#how-it-attacks">How it attacks</a> ·
  <a href="#command-reference">Commands</a> ·
  <a href="docs/OPERACION.md">Operations</a> ·
  <a href="docs/ARCHITECTURE.md">Design</a>
</p>

---

ANDRAS is not an awareness-training simulator that mails a list. It attacks **one named person**:
it harvests what is public about them, keeps a citation for every claim, ranks the hooks by pain
× provability, writes the sequence that lands hardest, and waits for you to approve it. Then it
runs the campaign across email, SMS, phone and Telegram — and changes channel when the previous
beat fails.

Everything stays local. SQLite on disk, hashed snapshots, testnet wallets, no SaaS in the middle.
Point it at Ollama and not even the dossier leaves the machine.

> **Local-first by design.** Nothing is sent without a human gate in front of it.

## What it is

- **A recon engine with receipts.** Every artifact stores URL, snapshot hash, timestamp and
  confidence. Two independent domains promote it to `corroborated`; anything only the LLM said
  stays `inferred` and never holds a hook on its own.
- **A planner you can argue with.** The full sequence — channel, pack, delay, trigger — is
  printed before a single message goes out. You confirm the plan; the first email is not the
  consent.
- **An adaptive operator.** Triggers (`no_visit`, `visited`, `no_reply`, `no_submit`) gate each
  next step, so silence reroutes the attack instead of repeating it.
- **A cloner.** HTTrack mirrors the real portal, the mirror is served under the campaign token,
  and credentials plus one-time codes land in the database.
- **An arsenal with limits written down.** 24 social-engineering tools catalogued by function;
  each card says what stops it here — Linux, root, same network — instead of pretending.

## What it is not

- Not a traffic proxy with live session theft. The clone is static; JavaScript logins and live
  sessions still need Evilginx.
- Not a cloud service. There is no hosted dashboard, no account, no telemetry.
- Not finished. This is alpha: the honest gaps are in [Limits](#limits) and
  [docs/DEPRECATED.md](docs/DEPRECATED.md).

## Why it exists

Manual phishing fails for two reasons: the hook is generic and the operator cannot say what
backs each sentence. ANDRAS attacks both. The agent does the boring collection and the first
draft; the human keeps judgement, budget and the send button.

## Features

| Area | What you get |
|---|---|
| Recon | Directed OSINT collectors, page triage, per-source confidence, budgets |
| Dossier | Structured claims, one `artifact_id` per assertion, snapshot with hash |
| Hooks | Ranking by pain × provability, never by how clever they sound |
| Plan | Per-channel vectors, critic pass, completeness contract |
| Campaign | 3–6 beats, channel mix, waits and failure triggers, resumable |
| Delivery | SMTP, Telegram, Twilio SMS/WhatsApp, manual fallback with ready-to-send text |
| Landing | Portal clone with credential and OTP capture, opaque per-campaign token |
| Execution | Detached daemon, jobs, backoff, desktop/Telegram alerts, signed webhooks |
| Evidence | `corroborated` / `inferred`, contradiction hunting in the critic |
| OPSEC | Burner → mixer → treasury wallets, network profiles, infrastructure burn |
| Memory | Per-mission journal, FTS search, export, per-vector notes |
| Interop | CLI, Textual TUI and wizard, Telegram bot, JSON config, YAML technique packs |

## Install

Requires Python 3.11+ on macOS or Linux. No LLM key? It still works in dumb mode (regex and
public records). With Ollama, nothing leaves the box.

```sh
git clone https://github.com/azazelumbrae/Andras.git && cd Andras
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'      # add '.[tui]' for the interface
cp .env.example .env                   # secrets here, never in config.json
cp config.example.json config.json     # set SMTP, base_url, llm
.venv/bin/andras init
.venv/bin/andras preflight             # environment traffic light
```

`preflight` checks Python, SQLite, `base_url`, SMTP/IMAP, LLM reachability, `hook_secret` and
the tools it can actually run. It tells you what is missing before a campaign does.

## Quickstart

```sh
.venv/bin/andras                       # wizard: environment, model, campaign, target
```

The wizard writes to the same tables as the CLI, so a plan built by hand shows up in the UI and
vice versa. Everything is scriptable:

```sh
andras mission new --name "Ana Pérez" --role CFO --company Acme --domain acme.com \
                   --goal "open the link and type credentials" --mode tracked
andras recon   --mission <id>          # OSINT + triage, under budget
andras dossier --mission <id>          # distill, keep provenance
andras hooks   --mission <id>          # propose and score hooks
andras hook-choose 2 --mission <id>
andras campaign plan --mission <id> --channels email,sms,phone --length 4
andras campaign show <plan_id>         # read the whole thing
andras plan confirm <plan_id>          # consent for its steps
andras campaign run  <plan_id> --to ana@acme.com
andras serve                           # landing, pixel, webhook receiver (second terminal)
andras debrief --mission <id>          # report in data/reports
```

`deliver` and `campaign run` ask for `SEND` on every send unless `ANDRAS_YES=1`.

## How it attacks

```
recon ──▶ dossier ──▶ hooks ──▶ plan ──▶ human review ──▶ execution ──▶ debrief
  │          │          │         │            │               │
OSINT     provenance  pain ×   channels +   you confirm   alerts + journal
+triage   per claim   proof    triggers      the plan      + budgets
```

1. **Recon** runs directed collectors and triages what comes back. Pages are snapshotted and
   hashed; robots, redirects and payload weight are noted.
2. **Dossier** distils the material into claims and binds each to an `artifact_id`.
3. **Hooks** score angles by how much they hurt × how well they are proven.
4. **Plan** turns the chosen hook into vectors per channel; the critic hunts contradictions,
   gaps and killer details.
5. **Review** prints the sequence and the evidence behind it. You confirm.
6. **Execution** runs with jobs, retries, spend caps and alerts.
7. **Debrief** closes with a report and an exportable journal.

Each phase writes to SQLite and the next one refuses to run without material.

## Evidence model

A finding is worth what its sources are worth.

- one source → `single_source`
- two independent domains → `corroborated`
- LLM inference only → `inferred`, never enough to anchor a hook alone

The critic runs before the send and flags what the dossier cannot support. No *smoking guns*:
three passive, checkable facts beat one spectacular unverified find.

## Permissions and budgets

The agent acts by class, not by vibes:

| Class | Examples | Gate |
|---|---|---|
| `read` / `write` | recon, notes, dossier | never |
| `send` | email, SMS, Telegram | needs a confirmed plan |
| `spend` | domains, wallets | above 0.25 USD |
| `admin` | DNS, infrastructure burn | always |

Defaults: **40 steps**, **300k tokens**, **3 USD**, **0.001 BTC** on testnet. Change them with
`set_budget` or in `config.json`.

Alerts on desktop and Telegram (`notify`): `hit` when the target folds, `critical` when a step
exhausts retries. The journal lives in `data/missions/<id>/journal.md`.

## The campaign engine

`campaign plan` is the core. The model receives the goal, the chosen hook with its support, and
the pack catalogue, then returns 3–6 beats with channel, pack, delay and trigger. A beat only
fires if the previous one missed:

`always` · `no_visit` · `visited` · `no_reply` · `no_submit`

- every beat gets its own full script on the same hook and the same artifact ids;
- `campaign show` prints all of it before anything leaves;
- `--skip-wait` walks the sequence without waiting, `--resume` picks up where it stopped;
- an adapter without credentials marks the send `failed` and prints the text plus tokenised link
  so you can send it by hand.

## Cloned landing and OTP

The training template fools nobody. For a real campaign, clone the real portal:

```sh
andras clone fetch https://portal.acme.com --mission <id> --depth 2
andras serve                                    # second terminal
andras clone attach <clone_id> <campaign_id>    # forms now go through ANDRAS
```

Every `<form>` is rewritten to `/<token>/__capture`, which stores username, password and
one-time code under the field names providers actually use, then shows the OTP screen. The
original `action` is kept in a hidden field. `clone list` shows captures; `clone drop` removes
the mirror.

The mirror is static and served from your machine: no external dependency at click time for the
assets HTTrack localised.

## Arsenal

`andras/toolbox.py` catalogues 25 social-engineering tools by function — cloning, proxy,
network, branding, capture, payload, agent — each with what it does, install line, usage and hard
limit. The agent consults the catalogue before promising a step.

```sh
andras toolbox list --category cloning
andras toolbox show httrack
andras toolbox check                   # what is missing and how to install it
andras toolbox run httrack https://portal.acme.com
andras toolbox image                   # build the Linux-only image, once
```

Everything is actually installed, not just catalogued:

- **Native on macOS:** HTTrack, bettercap, ettercap, sslsplit, tcpreplay, mitmproxy, dnschef,
  and the vendored tools behind `scripts/` launchers — Responder, evil-ssdp, DNSrebinder,
  EyeWitness, urlcrazy, Yersinia (compiled from source) and PicoClaw.
- **Inside the `andras/arsenal` image** (Kali base, built from `docker/arsenal.Dockerfile`):
  `set`, `beef-xss`, `msfpc`, `wifi-honey`, `fiked`, `evilgrade`, `sniffjoke`, `thc-ipv6`,
  `dsniff`, `tshark` and a `convoC2` compiled from source. `scripts/in-docker.sh` wraps them.
- Most want root or the same network as the target, and the card says so.

Only the whitelist runs from inside ANDRAS: `httrack`, `urlcrazy`, `eyewitness`. The container
tools are launched through the same `argv_for`, so a whitelist entry needs no special case.

## OPSEC

- The server binds to localhost and speaks plain HTTP: put your own tunnel in front.
- Opaque tokens per campaign; the form stores credentials in SQLite.
- Webhooks require HMAC-SHA256 when `hook_secret` is set; without it they are accepted in clear.
- Wallet seeds live in `data/andras.sqlite3`: lab, not production custody.
- `config.json`, `.env`, `data/` and snapshots stay out of Git: they carry target data.
- `authorized_recipients` scopes training; inside a mission the scope is the target.

Read [docs/OPERACION.md](docs/OPERACION.md) before a real campaign: SPF/DKIM/DMARC, IMAP
mailbox, `hook_secret`, an inspected clone, a network profile. Afterwards, export the journal and
burn the infrastructure.

## Command reference

| Command | What it does |
|---|---|
| `mission new/list/show/status` | mission lifecycle |
| `recon` | OSINT collectors + page triage |
| `dossier` | structured dossier with `artifact_id` per claim |
| `hooks` / `hook-choose` | hooks ranked by pain × provability |
| `plan` | single-channel vectors |
| `campaign plan/show/run` | multi-channel sequence with triggers |
| `critic` | contradictions, gaps, killer details |
| `build` | per-channel render and QA |
| `deliver` | real send and record |
| `debrief` | mission report in markdown |
| `clone fetch/attach/list/drop` | clone a portal and serve it with capture |
| `toolbox list/show/check/run/image` | social-engineering arsenal |
| `packs --validate` | check technique packs |
| `agent` | agent-driven recon and plan |
| `plan confirm/list` | grant consent or list plans |
| `run start/stop/status/pause/resume/abort` | execution daemon |
| `bot` | Telegram replies with the campaign script |
| `notes add/list/search/export` | campaign journal (`--attack` for one vector) |
| `wallet new/list` | burner, mixer and treasury |
| `net show/set/burn` | network profiles and infrastructure burn |
| `channels audit/dkim` | SPF/DKIM/DMARC for the sending domain |
| `tui` | terminal interface |
| `preview/send/serve/report` | simulator v1 |

## Techniques

The [unjail.ai](https://www.unjail.ai/how-jailbreaking-works) frameworks live in `prompts/packs/`
as versioned YAML: a 7-turn chain (recon, process intel, pretext, credibility, urgency,
authority, finisher) plus Dark Psychology, Crescendo and DRA as prompt layers. The chosen pack is
injected into the plan and a completeness contract forces the whole artifact.

## Configuration

`config.example.json` documents every key: SMTP/IMAP, `base_url`, `hook_secret`,
`capture_credentials`, `capture_otp`, LLM providers (`deepseek`, `ollama`), budgets, notifications,
network profiles and wallet endpoints. Secrets go to `.env`.

## Limits

- Without Twilio credentials, SMS and WhatsApp degrade to `failed` plus manual text.
- Without a real domain and IMAP, there is no genuine SPF/DKIM nor reply detection.
- Without `monero-wallet-rpc`, XMR swap and mixing stay a runbook; BTC is signed outside.
- Clones are static: JavaScript logins and live sessions need Evilginx.
- Alpha software. Expect sharp edges and read the code before a client campaign.

## FAQ

**Does my target's data leave the machine?** Only to the LLM you configure. Use Ollama to keep
even that local.

**Do I need Docker?** Not for the core. Docker is only needed for the Linux-only tools in the arsenal: `andras toolbox image` builds them once, `andras toolbox check` tells you what is missing.

**Can it send from a lookalike domain?** It audits SPF/DKIM/DMARC and tells you what to publish.
The `From` of a domain you do not own is never truly legitimate.

**How long does a campaign take?** As long as you tell it: waits are per beat and resumable.

## Contributing

Issues and PRs welcome. `ruff check andras tests` and `pytest` must stay green; CI runs both.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).

<p align="center"><sub>Use it only on your own or authorised targets.</sub></p>
