# Setup guide (no coding needed)

The system is already built. It lives in this GitHub repository and runs
itself every Monday morning on GitHub's free servers. It only needs two things from you:

1. A **Claude API key**, so it can analyse applications.
2. Your **email login**, so it can send the report.

Both are stored as **GitHub secrets**: encrypted values that only the weekly job
can read. Nobody can view a secret after it's saved, not even you.
**Never paste a key or password into a chat, email or file.** It only ever goes in
the GitHub secrets boxes described below.

---

## Step 1: Get a Claude API key (about 5 minutes)

An **API key** is a password that lets a program use Claude. It's separate from
a Claude.ai chat subscription and is billed pay-as-you-go.

1. Go to **https://console.anthropic.com** and sign up (or log in).
2. In the left menu click **Billing** and add a payment method plus some credit
   (e.g. $20, which should last several weeks).
3. Still in **Billing** (or **Limits**), set a **monthly spend limit**, e.g. $40.
   This is your safety net.
4. In the left menu click **API keys** → **Create key**. Name it `padeltech-leads`.
5. Click **Copy**. Keep this browser tab open; you'll paste the key in Step 2.
   (It's only shown once. If you lose it, delete it and create a new one.)

## Step 2: Add the secrets to GitHub (about 5 minutes)

1. Open this repository on GitHub.
2. Click **Settings** (top bar of the repository) → in the left menu
   **Secrets and variables** → **Actions**.
3. Click the green **New repository secret** button. Add these four, one at a time
   (type the *Name* exactly, paste the *Secret*, click **Add secret**):

| Name | Secret (what to paste) |
|---|---|
| `ANTHROPIC_API_KEY` | The key you copied in Step 1 (starts with `sk-ant-`) |
| `SMTP_USERNAME` | The full email address the report is sent **from**, e.g. `you@ffpartners.uk` |
| `SMTP_PASSWORD` | That mailbox's password (if your email provider offers "app passwords", create one and use it instead) |
| `EMAIL_TO` | Who receives the report. Several people? Separate with commas: `a@x.com,b@x.com` |

Your domain's email is hosted by **Purelymail**, which the system uses by default
(`smtp.purelymail.com`, port 465). If you send from a different provider, open the
**Variables** tab on the same page and add `SMTP_HOST` (e.g. `smtp.gmail.com`) and
`SMTP_PORT` (e.g. `465`).

## Step 3: Send a test email (about 5 minutes)

1. Click the **Actions** tab at the top of the repository.
   (If GitHub asks, click **I understand my workflows, go ahead and enable them**.)
2. In the left list click **Weekly PadelTech lead report**.
3. On the right click **Run workflow** → leave *mode* as **test** → click the green **Run workflow**.
4. Wait 3–8 minutes. A yellow dot means it's running; a green tick means done.
5. Check your inbox for an email starting **[TEST] Weekly padel leads**.
   It analyses only a small sample, so it costs pennies and doesn't affect the system's memory.

✅ Got the email? You're finished. The real report arrives every Monday morning.

❌ Red cross instead? Click the failed run → click **report** → scroll to the red
text. The last lines say what went wrong (usually a mistyped secret). Fix the secret
and run the test again.

---

## Week to week

* **Nothing to do.** The report arrives every Monday between about 6 and 7am, with the Excel lead database attached.
* The **first real report** covers roughly the last week, so it'll be longer than usual.
  From then on you only get new applications and meaningful changes.
* If a run ever fails you get a "⚠️ lead report failed" email, and GitHub also
  emails the repository owner. Nothing is lost: the next run catches up automatically.
* To change keywords, timings or scoring, see **README.md** (or ask Claude to do it).
