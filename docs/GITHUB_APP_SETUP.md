# GitHub Setup — PAT, Bot Identity (GitHub App), and the Setup Script

Everything GitHub-related in one place. Two credentials, one script:

| Credential | Used by | Attribution | Your effort |
|---|---|---|---|
| **PR credential** (`github-pat` secret) | the evolution job — clones the repo and opens PRs from its container | your account | a fine-grained PAT (Step 1, ~2 min). Skip it and the script falls back to your `gh` CLI token — fine for a first spin, unfit for anything durable |
| **GitHub App** (`github-app-key` + `github-app-config` secrets) | the quality agent — files quality issues | `<your-app>[bot]` | optional (without it, issues attribute to your account) |

Both are stored by `scripts/setup/setup_github.sh` (Step 4 below),
which also wires CI: Workload Identity Federation, the CI service
account, repo variables, labels, and branch protection.



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

## Summary

| What | Where |
|------|-------|
| GitHub App | `skill-evolution-lab-bot` (your GitHub account settings) |
| App config | `projects/$PROJECT_ID/secrets/github-app-config` (app_id, installation_id, repo) |
| Private key | `projects/$PROJECT_ID/secrets/github-app-key` |
| Bot identity | `skill-evolution-lab-bot[bot]` |
| Permissions | Issues, Pull requests, Contents (all Read & Write) |
