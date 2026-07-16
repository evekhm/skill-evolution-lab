# GitHub App Setup

The workflow agents (Quality Agent, Skill Evolution Agent) authenticate
to GitHub using a single GitHub App. Actions show as `skill-evolution-lab-bot[bot]`.



---

## Step 1: Create the app

Go to: https://github.com/settings/apps/new

| Field | Value |
|-------|-------|
| App name | `skill-evolution-lab-bot` (any name you choose) |
| Homepage URL | Your repo URL |
| Webhook active | **Uncheck** (not needed, agents are triggered by GitHub Actions) |

### Permissions (Repository)

| Permission | Access |
|-----------|--------|
| Issues | Read & Write |
| Pull requests | Read & Write |
| Contents | Read & Write |

Leave everything else as default. Click **Create GitHub App**.

---

## Step 2: Save the App ID and generate a private key

After creation:

1. Note the **App ID** (number at the top of the app settings page)
2. Scroll to **Private keys**, click **Generate a private key**
3. A `.pem` file downloads -- keep it, you'll need it in Step 4

---

## Step 3: Install the app on your repository

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

---

## Step 4: Store the private key in Secret Manager

```bash
source .env

gcloud secrets create github-app-key \
  --project=$PROJECT_ID \
  --replication-policy=automatic \
  --data-file=./skill-evolution-lab-bot.*.private-key.pem
```

Verify:
```bash
gcloud secrets versions access latest \
  --secret=github-app-key \
  --project=$PROJECT_ID | head -1
# Should print the PEM header line ("BEGIN RSA PRIVATE KEY")
```

---

## Step 5: Store App config in Secret Manager

```bash
source .env

gcloud secrets create github-app-config \
  --project=$PROJECT_ID \
  --replication-policy=automatic \
  --data-file=- <<EOF
{"app_id": YOUR_APP_ID, "installation_id": YOUR_INSTALLATION_ID, "repo": "your-org/your-repolity-lab"}
EOF
```

Replace `YOUR_APP_ID` and `YOUR_INSTALLATION_ID` with the values from Steps 2 and 3.

Verify:
```bash
gcloud secrets versions access latest \
  --secret=github-app-config \
  --project=$PROJECT_ID
# Should print: {"app_id": ..., "installation_id": ..., "repo": "..."}
```

No `.env` changes needed -- agents read everything from Secret Manager at runtime.

IAM access is already handled -- `deploy.sh` grants `secretmanager.secretAccessor`
to the default compute service account at the project level.

---

## Step 6: Delete the local .pem file

```bash
rm ./skill-evolution-lab-bot.*.private-key.pem
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

## Summary

| What | Where |
|------|-------|
| GitHub App | `skill-evolution-lab-bot` (your GitHub account settings) |
| App config | `projects/$PROJECT_ID/secrets/github-app-config` (app_id, installation_id, repo) |
| Private key | `projects/$PROJECT_ID/secrets/github-app-key` |
| Bot identity | `skill-evolution-lab-bot[bot]` |
| Permissions | Issues, Pull requests, Contents (all Read & Write) |
