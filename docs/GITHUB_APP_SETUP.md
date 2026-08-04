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
| 5. Repo variables | The 8 Actions variables the workflows read (`PROJECT_ID`, `REGION`, dataset/table ids, `WIF_PROVIDER`, `WIF_SERVICE_ACCOUNT`, `TEST_DATASET_ID`) |
| 6. PR credential | Stores `GH_PAT` (the Step 1 fine-grained PAT) as the `github-pat` secret — the evolution job opens PRs with it. Unset, it falls back to your gh CLI token with a warning |
| 7. Branch protection | main requires the Golden Eval + Load Test checks before merge |
| 8. Bot identity | With `GH_APP_*` set: stores `github-app-key` + `github-app-config` — quality issues then post as `<your-app>[bot]` |

Success signals in the output: every step prints `Created ...` or
`already exists (skipped)`, and the closing summary shows
`[8] Bot identity: CONFIGURED` (or the not-configured note if you
skipped the App).

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

One repo variable tells the workflows which GCP project serves Claude
on Vertex (it is NOT this repo's infra project if Claude models are
enabled elsewhere):

```bash
gh variable set CLAUDE_VERTEX_PROJECT_ID --body "<gcp project with Claude models enabled>"
```

The model pinned in the workflows (`--model` and
`ANTHROPIC_SMALL_FAST_MODEL`) must be enabled on that project — verify
with a `rawPredict` probe against the global endpoint before changing
either side.

The workflows authenticate as a dedicated service account
(`ARGUS_SERVICE_ACCOUNT` repo variable) holding exactly one role:
`roles/aiplatform.user` on the Claude project. Never point them at
the shared CI account — the agent can read its own credential file,
so the account's roles are the blast radius, and the CI account's
Secret Manager access reaches the repo's write-capable GitHub
credentials. Create it once:

```bash
gcloud iam service-accounts create argus-reviewer --project=<claude-project>
gcloud projects add-iam-policy-binding <claude-project> \
  --member="serviceAccount:argus-reviewer@<claude-project>.iam.gserviceaccount.com" \
  --role=roles/aiplatform.user
gcloud iam service-accounts add-iam-policy-binding \
  argus-reviewer@<claude-project>.iam.gserviceaccount.com \
  --project=<claude-project> --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/<wif-pool-name>/attribute.repository/<owner>/<repo>"
gh variable set ARGUS_SERVICE_ACCOUNT \
  --body "argus-reviewer@<claude-project>.iam.gserviceaccount.com"
```

Model auth reuses the WIF provider from this doc's Step 5 — no
Anthropic API key is stored anywhere.

### Updating the review standards

The standards (what to flag, what to skip, tone, comment-only
authority) live in the "Automated review standards" section of the
root `CLAUDE.md` — edit that file and merge; the next run picks it up.
The workflow prompts only describe mechanics (which command to run,
where to post) and rarely need changing.

### Renaming the bot

Four places: the app name in GitHub settings, `trigger_phrase` in
`claude-pr-review.yml`, the `ARGUS_LOGIN` env at the top of
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
| Reviewer credentials | repo Actions secrets `REVIEWER_APP_ID`, `REVIEWER_APP_PRIVATE_KEY`; repo variable `CLAUDE_VERTEX_PROJECT_ID` |
| Reviewer identity | `<your-reviewer-app>[bot]`, mentions via `@argus` |
| Reviewer permissions | Issues + Pull requests Read & Write, Contents Read-only |
