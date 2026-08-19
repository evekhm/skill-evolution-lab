# GitHub Setup — PAT, Bot Identity (GitHub App), and the Setup Script

Everything GitHub-related in one place. Two credentials, one script:

| Credential | Used by | Attribution | Your effort |
|---|---|---|---|
| **PR credential** (`github-pat` secret) | the evolution job — clones the repo and opens PRs from its container | your account | a fine-grained PAT (Step 1, ~2 min). Skip it and the script falls back to your `gh` CLI token — fine for a first spin, unfit for anything durable |
| **GitHub App** (`github-app-key` + `github-app-config` secrets) | the quality agent — files quality issues | `<your-app>[bot]` | optional (without it, issues attribute to your account) |
| **Reviewer App** (`REVIEWER_APP_ID` + `REVIEWER_APP_PRIVATE_KEY` Actions secrets) | the Argus reviewer workflows — reviews PRs, answers issues and `@argus` mentions | `<reviewer-app>[bot]` | optional (see [Reviewer app (Argus)](#reviewer-app-argus) below) |

The first two are stored by `scripts/setup/setup_github.sh` (Step 4
below), which also wires CI: Workload Identity Federation, the CI
service account, repo variables, labels, and branch protection. The
Reviewer App is configured by hand — its credentials go straight into
GitHub Actions secrets (see [Reviewer app (Argus)](#reviewer-app-argus)).



---

## Step 1: Create the PR credential (fine-grained PAT)

The evolution job runs in a Cloud Run container with no GitHub login;
it needs a token to `git clone` the repo and `gh pr create` the
evolved skill. The setup script stores it in Secret Manager as
`github-pat`; the job's deploy mounts it as `GH_TOKEN`.

**Why a dedicated fine-grained PAT** (this is GitHub's recommended
token type, and what the reference deployment uses):

- **Least privilege** — valid for exactly one repository and exactly
  two permissions; a leak exposes this repo's contents and PRs,
  never your account.
- **Explicit expiry** — it dies on a date you chose, loudly, instead
  of whenever your interactive `gh` login happens to rotate.
- **Independent of you day-to-day** — re-logging `gh`, changing
  machines, or revoking CLI sessions never breaks the deployed job.

Create it:

1. GitHub > avatar > **Settings** > **Developer settings** >
   **Personal access tokens** > **Fine-grained tokens** >
   **Generate new token**
2. Name it (e.g. `skill-evolution-lab-pr`), pick an expiration
   (up to 1 year — put the renewal date in your calendar)
3. **Repository access**: *Only select repositories* -> this repo
4. **Permissions > Repository permissions**:
   **Contents: Read and write**, **Pull requests: Read and write** —
   nothing else
5. Generate; copy the `github_pat_...` value immediately (shown only
   once). Keep it for Step 5.

    ```shell
   export GH_PAT=github_pat_...
   ```

(The gold standard is App installation tokens — short-lived, bot
identity — which the quality agent already uses for issues; minting
them per-PR is tracked as future hardening. The fine-grained PAT is
the recommended practice for a long-lived job credential like this.)

---

## Step 2: Create the app (the bot identity — optional)

Go to: https://github.com/settings/apps/new

| Field | Value |
|-------|-------|
| App name | `skill-evolution-lab-bot` (any name you choose) |
| Description | e.g. "Automation identity for the Skill Evolution Lab: files quality issues from the daily BigQuery quality report and comments on evolution dispatches. All actions appear as this bot instead of a personal account." (shown on the bot profile and install screen) |
| Homepage URL | Your repo URL |
| Webhook active | **Uncheck** (the app never receives events; it only authenticates outbound calls) |
| Where can this app be installed | Only on this account |

### Permissions (Repository)

| Permission | Access |
|-----------|--------|
| Issues | Read & Write |
| Pull requests | Read & Write |
| Contents | Read & Write |

Leave everything else as default. Click **Create GitHub App**.

---

## Step 3: Save the App ID and generate a private key

After creation:

1. Note the **App ID** (number at the top of the app settings page)

    ```shell
   export GH_APP_ID=123456
   ```
   
2. Scroll to **Private keys**, click **Generate a private key**
3. A `.pem` file downloads -- keep it, you'll need it in Step 5

```shell
export GH_APP_KEY_FILE=~/Downloads/your-app.2026-07-17.private-key.pem  # the downloaded key
   ```
---

## Step 4: Install the app on your repository

1. On the app settings page, click **Install App** (left sidebar)
2. Select your account
3. Choose **Only select repositories**
4. Pick your repo
5. Click **Install**

The URL after installation looks like:
```
https://github.com/settings/installations/12345678
```

That number is your **Installation ID**. Save it.

```shell
export GH_APP_INSTALLATION_ID=12345678   # number at the end of the install URL
   ```
---

## Step 5: Run the setup script (stores everything)

One script run stores everything. Export the inputs, then run:

```bash
bash scripts/setup/setup_github.sh
```

What the script configures, in order:

| Step | What it does |
|------|--------------|
| 1. Python deps | PyGithub, PyJWT, etc. for the helper tooling |
| 2. Labels | Issue labels the quality agent uses (`quality`, `routing`, `hallucination`, `prompt-gap`, `tool-error`) |
| 3. Workload Identity Federation | Pool + OIDC provider in your GCP project, scoped to your GitHub user/org — GitHub Actions authenticate to GCP with zero stored keys |
| 4. CI service account | `github-actions-fixer@<project>` with the roles the workflows need, bound to this repo via WIF |
| 5. Repo variables | The 8 core Actions variables the workflows read (`PROJECT_ID`, `REGION`, dataset/table ids, `WIF_PROVIDER`, `WIF_SERVICE_ACCOUNT`, `TEST_DATASET_ID`); Step 9 (`SETUP_ARGUS=1`) adds `CLAUDE_VERTEX_PROJECT_ID` and `ARGUS_SERVICE_ACCOUNT` |
| 6. PR credential | Stores `GH_PAT` (the Step 1 fine-grained PAT) as the `github-pat` secret — the evolution job opens PRs with it. Unset, it falls back to your gh CLI token with a warning |
| 7. Branch protection | main requires the Golden Eval + Load Test checks before merge |
| 8. Bot identity | With `GH_APP_*` set: stores `github-app-key` + `github-app-config` — quality issues then post as `<your-app>[bot]` |
| 9. Argus reviewer identity | With `SETUP_ARGUS=1`: iamcredentials API, `argusVertexPredict` custom role, `argus-reviewer` SA, WIF binding, and the `CLAUDE_VERTEX_PROJECT_ID` + `ARGUS_SERVICE_ACCOUNT` repo variables (see [Reviewer app (Argus)](#reviewer-app-argus)) |

Success signals in the output: every step prints `Created ...` or
`already exists (skipped)`, and the closing summary shows
`[8] Bot identity: CONFIGURED` and `[9] Argus reviewer identity:
CONFIGURED` (or the not-configured notes for whichever optional
steps you skipped).

Run it BEFORE deleting the `.pem` (Step 6). Verify:

```bash
gcloud secrets describe github-app-config --project=$PROJECT_ID
gcloud secrets describe github-app-key --project=$PROJECT_ID
```

No `.env` changes needed -- agents read everything from Secret Manager
at runtime. IAM access is already handled -- `deploy.sh` grants
`secretmanager.secretAccessor` to the default compute service account
at the project level.

---

## Step 6: Delete the local .pem file

ONLY after Step 5's verify shows both secrets exist:

```bash
rm ~/Downloads/your-app.*.private-key.pem
```

The private key now lives only in Secret Manager.

---

## How agents authenticate at runtime

Agents generate short-lived installation tokens (valid 1 hour):

```python
import jwt, time, requests
from google.cloud import secretmanager

def get_installation_token(project_id, app_id, installation_id):
    client = secretmanager.SecretManagerServiceClient()
    key_pem = client.access_secret_version(
        request={"name": f"projects/{project_id}/secrets/github-app-key/versions/latest"}
    ).payload.data.decode("utf-8")

    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 600, "iss": app_id}
    token = jwt.encode(payload, key_pem, algorithm="RS256")

    resp = requests.post(
        f"https://api.github.com/app/installations/{installation_id}/access_tokens",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
    )
    resp.raise_for_status()
    return resp.json()["token"]
```

Use with PyGithub:

```python
from github import Github

token = get_installation_token(PROJECT_ID, APP_ID, INSTALLATION_ID)
g = Github(token)
repo = g.get_repo("your-org/your-repo")
```

---

## Rotating the key

If the private key is compromised:

1. Go to app settings, generate a new private key
2. Add new version to Secret Manager:
   ```bash
   gcloud secrets versions add github-app-key \
     --project=$PROJECT_ID \
     --data-file=./new-key.pem
   ```
3. Disable the old version:
   ```bash
   gcloud secrets versions disable OLD_VERSION \
     --secret=github-app-key \
     --project=$PROJECT_ID
   ```
4. Delete the local file

No code changes needed -- agents always read `versions/latest`.

---

## If the evolution job's PRs start failing with auth errors

Either the fine-grained PAT hit its expiry date, or (if you used the
gh-token fallback) your `gh` login rotated. Same fix for both: create
a fresh token per Step 1, then:

```bash
gcloud secrets delete github-pat --project=$PROJECT_ID --quiet
export GH_PAT=github_pat_...
bash scripts/setup/setup_github.sh
```

---

## Reviewer app (Argus)

A second, separate GitHub App gives the automated reviewer
(`.github/workflows/claude-pr-review.yml` and
`claude-hourly-sweep.yml`, both running `anthropics/claude-code-action`
on Claude via Vertex AI) its own bot identity. Named after Argus
Panoptes, the hundred-eyed watchman — reviews post as
`<your-reviewer-app>[bot]`.

Keep it separate from the quality-agent app above: the reviewer is
comment-only and never needs Contents write, so a leaked reviewer
credential cannot touch code.

### Goal and design philosophy

The goal is a review pipeline where nothing merges on one model's
opinion. Every PR and issue is reviewed by two agents from two model
families — Argus (Claude on Vertex AI, event-driven, seconds of
latency) and Atlas (Gemini, polled from the owner's private
environment) — and a security or bug finding closes only when both
explicitly agree. Different model families have different blind
spots, and cross-checking catches defects a single reviewer misses.
The protocol keeps disagreements open until evidence settles them or
the owner does.

Design rules the implementation follows:

1. **Authority lives in code, not prompts.** The model only writes
   findings JSON. A deterministic step
   (`scripts/ci/argus_post_review.sh`) performs every GitHub write:
   review events are hardcoded to `COMMENT` (approving, blocking,
   closing, or merging is impossible by construction), the sweep's
   `Reviewed-head` marker is appended by code, and the ledger and
   labels are updated from validated JSON. A prompt-injected agent
   can change the text of its findings but cannot make the pipeline
   perform an action outside this fixed set.
2. **Least privilege at every layer.** The GitHub App holds Contents
   read-only + Issues/PR write; the GCP service account holds one
   custom role (`aiplatform.endpoints.predict` — predict, nothing
   else); agent tool allowlists expose read-only `gh`/`git` commands;
   the WIF credential file is moved out of the workspace before the
   agent starts; the trusted script executes only after its sha256
   matches the hash recorded before the agent ran. The assumption
   throughout: the agent reads untrusted text and can be subverted,
   so what it *can reach* is the security boundary, not what it is
   *told to do*.
3. **Evidence arbitrates, never identity.** Neither reviewer defers
   to the other; re-running a claim outranks arguing about it;
   conceding without new evidence is a protocol violation; an
   escalated disagreement is a good outcome, not a failure.
4. **The ledger is both state and dataset.** Every finding's row ends
   in an outcome (`agreed`, `conceded-by-argus`, `conceded-by-atlas`,
   `escalated`), so over time the ledger measures the reviewers
   themselves — dispute rate, concession direction, escalation rate.

### Setup checklist (in order)

1. **Create the reviewer GitHub App** and install it on the target
   repository only — the bot identity and its comment-only
   permissions ("Create and install" below).
2. **Store the credentials**: the app id and private key go into the
   `REVIEWER_APP_ID` and `REVIEWER_APP_PRIVATE_KEY` Actions secrets;
   the workflows mint 1-hour installation tokens from them ("Store
   the credentials" below).
3. **Create the GCP identity**: run
   `SETUP_ARGUS=1 bash scripts/setup/setup_github.sh`. Step 9 enables
   `iamcredentials.googleapis.com` on the GCP project serving Claude models, creates the
   `argusVertexPredict` custom role and the `argus-reviewer` service
   account, binds WIF, and sets the `CLAUDE_VERTEX_PROJECT_ID` +
   `ARGUS_SERVICE_ACCOUNT` repo variables (details and guards in the
   section below).
4. **Ship the workflows** — `claude-pr-review.yml` (same-repo PR
   auto-review, new-issue response, `@argus` mention replies; each
   job pairs an agent step with a trusted posting step) and
   `claude-hourly-sweep.yml` (hourly catch-all: answers missed
   issues itself, dispatches missed PRs back to the event pipeline
   so ledger and labels have exactly one writer). Both are in
   `.github/workflows/`; nothing to configure beyond the secrets and
   variables above.
5. **No label or script setup is needed** — the trusted posting
   script `scripts/ci/argus_post_review.sh` self-creates the
   `argus:*` / `consensus:*` labels on first run.
6. **Adjust the standards, not the workflows**: review standards
   live in the root CLAUDE.md ("Automated review standards", "Peer
   review and consensus"). Install the peer reviewer's standing
   instructions (next section) in its runner.
7. **Shakedown before merge**: open the PR that introduces the
   reviewer and let it review that PR — `pull_request` workflows run
   from the PR's own branch, so the whole pipeline (auth, model,
   trusted step, ledger, labels) is exercised end to end before it
   reaches `main`. Issue response, mentions, and the sweep activate
   only after the merge.

### Create and install

Same flow as Steps 2–4 above, with these values:

| Field | Value |
|-------|-------|
| App name | e.g. `odyssey-argus` (globally unique on GitHub; the `[bot]` suffix is added automatically) |
| Webhook active | **Uncheck** |
| Permissions | **Contents: Read-only**, **Issues: Read & Write**, **Pull requests: Read & Write** — nothing else |

Install it on this repository only. No Installation ID needed — the
workflows discover it when minting tokens.

### Store the credentials (GitHub Actions secrets, not Secret Manager)

The workflows mint short-lived installation tokens directly with
`actions/create-github-app-token`, so the key lives in repo Actions
secrets:

```bash
gh secret set REVIEWER_APP_ID --body "<app id from the app settings page>"
gh secret set REVIEWER_APP_PRIVATE_KEY < ~/Downloads/<your-app>.*.private-key.pem
rm ~/Downloads/<your-app>.*.private-key.pem
```

The GCP side (project variable + a dedicated least-privilege service
account) is one script run. Note it re-executes Steps 1–8 too, which
is not purely additive: Step 5 rewrites the 8 core repo variables
from your local `.env`, and Step 7 resets branch protection to
exactly the Golden Eval + Load Test checks — if you have added
required checks since, re-add them after.

```bash
export SETUP_ARGUS=1
# The project where Claude models are enabled — defaults to PROJECT_ID.
# The model pinned in the workflows (--model and
# ANTHROPIC_SMALL_FAST_MODEL) must be enabled on it; verify with a
# rawPredict probe against the global endpoint before changing either.
export CLAUDE_VERTEX_PROJECT_ID="my-gcp-project"
bash scripts/setup/setup_github.sh
```

Step 9 of the script enables `iamcredentials.googleapis.com` on the
GCP project serving Claude models (the WIF impersonation exchange
needs it there — a hard failure when it differs from the infra
project),
creates the `argusVertexPredict` custom role
(`aiplatform.endpoints.predict` only — NOT the mutating
`roles/aiplatform.user`, which can create and delete Vertex resources
including this repo's reasoning engines), creates the
`argus-reviewer` service account with that single role, binds WIF,
and sets the `CLAUDE_VERTEX_PROJECT_ID` and `ARGUS_SERVICE_ACCOUNT`
repo variables.

Never point the workflows at the shared CI account instead — the
agent can read its own credential file, so the account's roles are
the blast radius, and the CI account's Secret Manager access reaches
the repo's write-capable GitHub credentials. Stated precisely, the
residual with the custom role: `aiplatform.endpoints.predict` is
bound project-wide, so a credential read from a run reaches inference
(spend) on any model or endpoint in the GCP project serving Claude models — not data or
configuration, and not the Agent Engine (querying it needs
`aiplatform.reasoningEngines.query`, which the role does not grant). The workflows fail fast
with a pointer here when `ARGUS_SERVICE_ACCOUNT` or
`CLAUDE_VERTEX_PROJECT_ID` is unset; an empty value would otherwise
pass auth silently and die at the first Vertex call, after the
tracking comment is posted. On re-runs, an existing
`CLAUDE_VERTEX_PROJECT_ID` repo variable is preserved unless you
export a different value explicitly — the script prints the change
when it makes one, along with the cleanup commands for the previous
project's now-orphaned `argus-reviewer` account. The export is
captured before the script sources `.env`; `.env` is not a supported
source for this variable. Three aborts protect the setting. Two are free (they fire before
Step 1 runs anything): the placeholder guard — pasting the snippet
above with the literal `"my-gcp-project"` unchanged stops the run
immediately (that literal is kept in sync between the snippet and
the guard in `setup_github.sh`) — and the `.env` guard, which stops
when `.env` sets a `CLAUDE_VERTEX_PROJECT_ID` the script would not
use (a `.env` value that merely matches the live repo variable is
inert and only warns). The third is inside Step 9: a repo-variable
lookup that fails for any reason other than "not set" (rate limit,
missing token scope) stops with the `gh` error rather than guess — a
failed lookup treated as absent would silently repoint the reviewer
at the infra project. That one is not free: by the time it fires,
Steps 1–8 have already rewritten the core variables and reset branch
protection.

Model auth reuses the WIF provider from this doc's Step 5 — no
Anthropic API key is stored anywhere.

### Review output, ledger, and consensus

The review agent posts nothing itself. It writes structured findings
JSON; a trusted workflow step (`scripts/ci/argus_post_review.sh`,
running with the app token) does every GitHub write: it posts the
inline-commented PR review (`event=COMMENT` hardcoded — approving or
requesting changes is impossible by construction), appends the
`Reviewed-head: <sha>` marker the sweep depends on, maintains the
"Argus findings ledger" comment, and applies labels. The script also
self-creates its labels, so no setup step is needed for them:

- `argus:findings` / `argus:clean` — Argus's own verdict.
- `consensus:pending` / `consensus:agreed` / `consensus:disputed` —
  the joint state with the peer reviewer. Only security and bug
  findings require both reviewers' agreement; suggestions are
  recorded in the ledger but never block `consensus:agreed`.

The ledger comment carries machine state in an embedded JSON block;
each row ends in an outcome (`agreed`, `conceded-by-argus`,
`conceded-by-atlas`, `escalated`) — over time this is a dataset of
reviewer-quality measurements: dispute rates, concession direction,
escalation rate.

### Peer reviewer: Atlas

Atlas (`evekhm-atlas-bot`, a machine user with write access) is the
second reviewer, running Gemini from a private environment of the
owner's on an hourly poll. AGENTS.md ("Peer review and consensus")
is the canonical protocol definition; the mention-job prompt carries
the conversation mechanics; and the block below is the copy of
Atlas's standing instructions — install it in Atlas's runner
configuration and keep it in sync with AGENTS.md (when they
disagree, AGENTS.md wins):

```text
## Dual review with Argus (evekhm-odyssey-argus[bot]) on evekhm/skill-evolution-lab

- Every open PR and issue is reviewed by BOTH you and Argus. The goal
  state is consensus: every security/bug finding explicitly agreed by
  both reviewers. Suggestions do not require your verdict.
- INDEPENDENCE: form your own findings FIRST, before reading Argus's
  review or the "Argus findings ledger" comment. Only then reconcile:
  mark AGREE or DISPUTE per Argus finding ID (e.g. R3-1) and add
  findings it missed as AT-1, AT-2, ... Never let its findings become
  your starting point.
- VERIFICATION over re-derivation: when a finding rests on a claim
  you can execute (a command, a reproduction, a line reference at the
  stated SHA), run it and report the actual output. A reproduced or
  refuted claim outranks any argument.
- REVIEW VERDICTS: when posting a PR review, always use COMMENT —
  never APPROVE, never REQUEST_CHANGES. Blocking verdicts are gating
  acts reserved for the owner and CI; a bot verdict also goes stale
  and blocks merges after the findings are fixed.
- RECORDING: verdicts you post as formal PR reviews are ingested by
  Argus automatically (the workflow subscribes to
  pull_request_review). Verdicts you post as ISSUE comments must
  include "@argus" or they are invisible to the ledger.
  Suggestion-only and clean reviews need no verdict at all — labels
  resolve on their own. Argus will not reply to a pure agreement:
  silence after your AGREE verdict means consensus is recorded — do
  not follow up.
- Disputes continue until resolved on evidence. Reply when Argus
  disputes your finding or counters your dispute; every reply MUST
  add new evidence. Do not agree in order to converge — dropping a
  position without new evidence is a protocol violation. If you have
  no new evidence, concede explicitly or escalate: two-line summary
  of both positions, tag @evekhm, stop. Tag conversational replies
  [argus<->atlas N] — N is PER THREAD: 1 + the highest tag anywhere
  in the thread, whoever posted it; never reuse a number. If N would
  exceed 10, escalate regardless.
- VERDICT FORMAT: one line per plain AGREE (finding ID + one line of
  verification evidence); full prose only for disputes, amendments,
  and new findings. Never assert ledger or label state ("the ledger
  can be marked agreed"); Argus's trusted step derives that state
  from recorded verdicts.
- Argus's review comments are not "unaddressed comments" needing a
  reply outside this protocol; never post acknowledgment-only
  comments (explicit AGREE/DISPUTE verdicts are required and do not
  count as acknowledgments).
- Write every comment self-contained (finding IDs, head SHA,
  evidence). You have no memory across runs; the thread is your
  memory. Argus replies within seconds; you reply on your next poll.
- State the head SHA you reviewed in every report header; line
  references must match it (review the PR branch, never main).
- Authority: comment only. Never approve, merge, close, reopen, or
  edit PRs/issues; never push.
```

### Updating the review standards

The standards (what to flag, what to skip, tone, comment-only
authority) live in the "Automated review standards" section of the
root `CLAUDE.md` — edit that file and merge; the next run picks it up.
The workflow prompts only describe mechanics (which command to run,
where to post) and rarely need changing.

### Renaming the bot

Four places: the app name in GitHub settings, the `"@argus"`
literals in `claude-pr-review.yml`'s mention job (its `if:` gate and
prompt), the `ARGUS_LOGIN` env at the top of
`claude-hourly-sweep.yml` (the app slug — the sweep matches it with
the `[bot]` suffix optional, because GraphQL output omits the suffix
while REST includes it), and the CLAUDE.md section header.

### Security notes (public repo)

- `pull_request` runs from forks get no secrets and no OIDC token, so
  the auto-review job is gated to same-repo PRs. Do not "fix" a fork
  PR not being reviewed by switching to `pull_request_target` with a
  head checkout at the workspace root — that executes untrusted code
  with base-repo credentials. Review fork PRs by commenting `@argus`
  yourself (the action only accepts triggers from actors with write
  access). Residual risk to keep in mind: that gate vets the human
  who typed the mention, not the fork's content — the agent then
  reads fork-authored text with base-repo credentials present on the
  runner. Treat `@argus` on a fork PR as running the reviewer on
  untrusted input, and read its output accordingly.
- Bot-authored comments never trigger the action (default
  `allowed_bots` is empty), so Argus cannot loop on itself.
- Code write access is impossible: the reviewer app has Contents:
  Read-only, so it cannot push, branch, or merge. Note that its
  Issues and Pull-requests write permissions cover more than
  comments (close/reopen, labels, edits) — comment-only behavior at
  that layer is enforced by the CLAUDE.md authority rules plus the
  workflows' tool allowlists, which expose no `gh` write command
  beyond commenting and no unrestricted `gh api`. Allowlist hygiene:
  entries are prefix matches with no argument inspection, so before
  adding one, check the command has no flag that executes an
  arbitrary program OR reads an arbitrary path. Both cases were
  proven by Argus on its own runners: `git fetch --upload-pack=<cmd>`
  executed commands (entry removed), and `git diff --no-index <path>`
  read the WIF credential file. Moving that file out of the workspace
  closed the git vector but only narrowed the read — the harness file
  tools are not path-scoped, and a job cannot hide a credential from
  itself. That is why the reviewer's service account holds a single
  role: its permissions are the real boundary.

---

## Summary

| What | Where |
|------|-------|
| GitHub App | `skill-evolution-lab-bot` (your GitHub account settings) |
| App config | `projects/$PROJECT_ID/secrets/github-app-config` (app_id, installation_id, repo) |
| Private key | `projects/$PROJECT_ID/secrets/github-app-key` |
| Bot identity | `skill-evolution-lab-bot[bot]` |
| Permissions | Issues, Pull requests, Contents (all Read & Write) |
| Reviewer App | e.g. `odyssey-argus` (your GitHub account settings) |
| Reviewer credentials | repo Actions secrets `REVIEWER_APP_ID`, `REVIEWER_APP_PRIVATE_KEY`; repo variables `CLAUDE_VERTEX_PROJECT_ID`, `ARGUS_SERVICE_ACCOUNT` |
| Reviewer GCP identity | `argus-reviewer@<gcp-project>` — custom role `argusVertexPredict` (`aiplatform.endpoints.predict` only), created by `SETUP_ARGUS=1 setup_github.sh` |
| Reviewer identity | `<your-reviewer-app>[bot]`, mentions via `@argus` |
| Reviewer permissions | Issues + Pull requests Read & Write, Contents Read-only |
