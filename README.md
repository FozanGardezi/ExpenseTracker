# Expense Tracker

Replaces manual budget tracking: it builds your spending history automatically
from the emails in your Gmail.

Users **continue with Google** and **give the app permission to read their
Gmail (read-only)**. Before Google's screen, the app explains exactly what it
will read and asks them to confirm. Every user's data is kept apart from
everyone else's.

- **Banks and wallets**: you choose the ones you use (HBL, Meezan, JazzCash,
  NayaPay, or any other by its sender), and the app reads their transaction
  alert emails.
- **Delivery services**: Foodpanda, Careem, inDrive and Krave Mart receipts,
  with restaurant and ride details.

Both go into one list of money in and out. A card or wallet payment for a
delivery order is matched to that order and counted once. A transaction with
no matching order (a bill, groceries, a transfer to a friend) is added on its
own. A delivery order with no matching transaction (cash, or an account you
haven't added) still counts, from its receipt.

- **What the emails miss**: **Add expense** takes cash spending (samosas,
  roti) typed in, or a bank's SMS or app notification pasted in, which is read
  the same way as an alert email.
- **A monthly budget**: how much has gone out and per day, the month against
  your budget (on track, heading over, over), limits on parts of it (eating
  out, petrol, one coffee shop), past months side by side, and **Keep an eye
  on**: places and categories well above their usual, and habits like the same
  coffee shop fourteen times a month.

None of these services offers a public API for this data, so emails are the
source. The order parsing started from
[FoodpandaExpenseTracker](https://github.com/fasi96/FoodpandaExpenseTracker).

## The phone app

Expense Tracker is a **native app for iPhone and Android**, built with
[Expo](https://expo.dev) (React Native), in `mobile/`. The same code also runs
in a browser. The app talks to a small **API server** (`api/`, FastAPI), which
does the work it always did, with the same Python code (`order_tracker/`):
Continue with Google, reading Gmail and statement PDFs, matching payments to
orders, budgets and what stands out. The original **Streamlit website**
(`app.py`) still works on that same code and data, so you can use either.

```
phone app (mobile/) ──HTTPS──▶ API (api/) ──┐
                                            ├──▶ order_tracker/ ──▶ Gmail, data/users/<id>/
website (app.py) ───────────────────────────┘
```

Why it's built this way:
- **Gmail stays on the server.** The read-only Gmail permission and its
  long-lived token never reach the phone. Syncing runs on the server, where it
  can take minutes over a year of email, and the cron job keeps working when
  the app is closed. iOS stops apps from doing that work in the background.
- **One codebase, both platforms.** The app is TypeScript, and Expo builds and
  signs the iOS and Android apps in the cloud (no Mac needed), ships updates
  over the air, and runs the same code in a browser.
- **Nothing to re-learn.** Every figure comes from the same tested Python as
  before. Each screen has one endpoint that works out what the screen shows,
  and the app lays it out.

See [Setup](#setup) to run both, and [Trying it on a phone](#trying-it-on-a-phone).

## Pages

Four tabs, each with sub-tabs. The introduction and the controls are only on
Home; the other tabs are just your data and settings. It's laid out like a
banking app: cards, lists you tap (a payment opens in a sheet), light and dark
themes that follow your system (or **Settings → Appearance** in the app, the ⋮
menu on the website). In the phone app the four tabs are the tab bar at the
bottom and the sub-tabs a switch at the top. Where the website edits many rows
at once in a table (Transactions, Statements, Transfers), the app changes one
payment at a time in its sheet, and **Export CSV** saves or shares the list. On
the website, columns stack on a phone and the tabs fold into a menu.

| Tab | Sub-tabs | What's there |
|---|---|---|
| **Home** | – | Greeting, Gmail status and last sync, **Add expense**, **Sync now**, **Sync options** (sources, look-back, re-scan, *Read older statements*), setup steps (until done). |
| | **Overview** | One month (this month unless you pick another): how much you've spent and per day, with *Mine* and *Home*; the month against your **budget** with how it was worked out; your **limits**; **Where it went** (a donut and each category against its usual); **Keep an eye on**; the latest payments. **For** switches to one label, e.g. only *Home*. Tap a category, limit or item to list its payments; tap a payment to change it. |
| | **Trends** | Past months split by category with your budget as a dashed line (tap part of a month for its payments), your usual, highest and lowest month, each category this month against its usual with its last six months, and a month-by-month table. |
| | **Places** | Everywhere you paid, by amount or by how often, with the last six months. **Find a place** ("double shot") to see what it costs you a month; open one to set a monthly limit for it. |
| | **Budget** | Your monthly budget and limits: a category, places with certain words, or both. Changes apply from this month; earlier months keep the budget they had. |
| **Activity** | **Transactions** | Everything, as a list by day (tap a payment to change it, add a note, or remove something you added) or as a table to change many rows' category, **For**, **In spending** and **Note** in place. Search; filter by period, category and source. |
| | **Statements** | Spending for each month from your monthly statements. Click a month's bar (or pick it) to see its totals, spending by category, and every transaction, whose category, For, In spending and note you can change. |
| | **Transfers** | Money you sent by transfer, the limit up to which transfers count as spending, and an **In spending** tick, category, For and note for each. |
| | **Delivery orders** | Foodpanda, Careem, inDrive and Krave Mart: by service, by merchant, every order. |
| **Accounts** | **Banks & wallets** | Which banks and wallets to track, and how their emails are found. |
| | **Statement settings** | Per bank: statements on/off, PDF password, sender; statements read and any that couldn't be. |
| | **Import** | Your full foodpanda history from your account, and CSV files of order history. |
| **Settings** | **Gmail & account** | Who's signed in, **Sign out**, the Gmail permission (allow / **Disconnect**), **Delete my data**. |
| | **Categories** | Your **rules** (merchant words, category and amount range → a category and/or who it was for), your own categories, and who you spend for (*Mine, Home* by default). |
| | **Skipped emails** | Emails from tracked senders that weren't counted, and why. |
| | **Privacy** | What the app collects and why (also public at `/privacy`). |

Each sub-tab has its own address (for example `/activity?activity=Statements`
on the website, `/activity?tab=statements` in the app), so it can be linked to
and bookmarked.

## Continue with Google and the Gmail permission

1. A visitor sees what the app will read (which senders), what it will never do,
   and how to withdraw access. They must tick *"I've read this and allow the app
   read-only access to my Gmail"* before **Continue with Google** is enabled.
2. Google's consent screen asks for their name and email address (`openid email
   profile`) and **read-only Gmail** (`https://www.googleapis.com/auth/gmail.readonly`).
   Nothing else is requested.
3. When Google sends them back, the app:
   - checks the signed `state`, which expires after 10 minutes;
   - verifies Google's ID token to learn who the user is;
   - checks the Gmail permission was actually granted. Google lets users untick
     it, and then they're signed in but no email is read until they allow it on
     **Settings → Gmail & account**.
4. The long-lived Gmail token is stored **encrypted** (Fernet) in the user's own
   directory, `data/users/<id>/`, next to their database. It keeps syncing
   working in the background.
5. **Returning users** stay signed in on that browser for 30 days. After *Continue
   with Google*, the browser keeps a random token in a cookie; the server stores
   only its SHA-256 hash, with an expiry (`data/sessions.db`). Reloading the app
   signs the user straight back in. The cookie is set from the page, so it isn't
   HttpOnly; anyone with access to that browser profile could use it until it
   expires or the user signs out.
6. **Disconnect Gmail** revokes the permission at Google and deletes the token.
   **Delete my data** removes the user's whole directory. **Sign out** deletes the
   remembered sign-in and clears the cookie; it doesn't withdraw Gmail access.

**In the phone app** the steps are the same, with Google's screen in the phone's
browser (Google doesn't allow it inside an app). The API handles Google's answer
at `/auth/google/callback`, then sends the browser back to the app
(`expensetracker://auth`) with a one-time code. The app swaps it for a session
token, which stays in the phone's Keychain or Keystore (expo-secure-store) for up
to 180 days; the server keeps only its hash. The swap also needs a secret the
app made up before opening Google (PKCE), so another app that catches the
redirect can't use the code. **Sign out** forgets that phone's token only.

Gmail has no permission limited to particular senders, so `gmail.readonly`
covers the whole mailbox. The app only ever *requests* emails matching the
searches shown on the Gmail access page. The consent text says this plainly.

The app doesn't use Streamlit's built-in `st.login`, so there's no `[auth]`
section or cookie secret to configure.

## How it avoids counting things twice

- **Payment ↔ order**: a debit is linked to a delivery order when the amounts
  match (within 1 unit of currency) and the times are within 2 hours. If the
  alert names the service (e.g. "FOODPANDA"), they only need to be within 48
  hours, since some banks send the alert when the payment settles.
- **Transfers aren't assumed to be spending**: money sent to a person or another
  account (IBFT, Raast, JazzCash, "sent to …") is categorised *Transfers* and
  isn't counted as spending, because it might be rent, a loan or savings. On
  **Activity → Transfers** you can count transfers up to a limit as spending
  (handy for paying shops or rickshaws by wallet), and any transfer you tick
  **In spending** or give a real category (Rent, Going out…) counts whatever
  its size. Home → Overview shows how much in transfers isn't counted.
- **Rules** (**Settings → Categories**) set the category, who it was for, or
  both, for money going out: e.g. *"euro store" from 5,000 → Groceries for
  Home* and *"euro store" → Food for Mine*. When several match, the one with
  the most conditions wins (then the higher one). A change you make to a single
  transaction always beats rules. A "For" rule can also match on category
  (*Bills & utilities → Home*), including categories you picked by hand.
- **Who it was for**: every payment is for one of your labels (*Mine* and
  *Home* unless you change them). The first label is used until a rule or you
  say otherwise.
- **Expenses you add**: cash is never paired up as a move between your own
  accounts. A pasted message is stored once however often it's pasted, and an
  email alert for a payment you already added (same account, direction and
  amount, within a day) isn't stored again. Adding one that looks like a
  payment already there asks you first.
- **Moves between your own accounts**: a debit in one tracked account and a
  credit of the same amount in another, within 2 hours (e.g. Meezan → JazzCash),
  form an internal transfer. Both sides are left out of spending and income.
  You can show them on **Activity → Transactions**.
- **Duplicate emails**: an order's "placed" and "delivered" emails count once
  if they share an order number. Orders from different sources (Gmail, foodpanda
  account, CSV) also merge when one lacks a number and the amount and time match
  within 3 hours. A bank alert with a reference number is stored once.
- **Alert ↔ statement**: a statement row and an alert for the same money
  movement (same bank, direction and amount, within 3 days, since statements
  often list the posting date) count once. The alert is kept because it has the
  exact time. Statement rows with no alert are added, which fills in what the
  alerts missed.

## Banks and wallets

On **Accounts → Banks & wallets**, pick from the common ones (HBL, Meezan, UBL, MCB, Bank
Alfalah, Allied, Bank AL Habib, Faysal, Askari, Standard Chartered, JS Bank,
HabibMetro, Dubai Islamic, JazzCash, Easypaisa, NayaPay, SadaPay, UPaisa,
Payoneer, PayPal, Wise), or add your own:

- **Sender**: copy it from one of the bank's alert emails. A full address
  (`alerts@bank.com`), a domain or a word from the sender's name all work.
- **Only subjects containing** (optional): use this when the same sender also
  emails statements or promotions, e.g. `Transaction Alert`.
- **Currency**: used when an alert shows a bare amount.

The presets match by name ("meezan" matches "Meezan Bank
<anything@meezanbank.com>"). Use **Check what the app searches for** to copy the
exact Gmail search into Gmail and see which emails it finds.

**Many Pakistani banks and wallets send SMS alerts only, by default.** Turn on
email alerts in the bank's or wallet's app or internet banking, or the app will
have nothing to read.

### How alerts are read

Alert wording differs by bank, so there is no template per bank.
`order_tracker/alerts.py` looks for what every alert contains:

- **The amount**: amounts labelled "balance", "available", "limit" or "due" are
  ignored. If the alert has no currency, it falls back to "Amount: 1,250".
- **The direction**: "debited", "spent", "paid to" and "sent" mean money out;
  "credited", "received from", "refund" and "salary" mean money in. These words
  are read from the subject and the text around the amount, not the footer.
  "Credit card" doesn't count as money in.
- **The merchant or person**: "Merchant: X", "Beneficiary: X", "at X", "to X",
  "from X".
- **A reference number**, used to avoid storing the same transaction twice.

Subjects about OTPs, statements, logins, declined or failed transactions and
promotions are skipped. Categories come from keyword rules in
`order_tracker/categories.py` (fuel stations such as PSO, Shell and Total are
*Fuel*), then your own rules under **Settings → Categories**, and you can change
any of them on **Activity → Transactions** or **Activity → Statements**.
Transactions stored as *Other* are guessed again whenever the built-in keywords
improve.

**This has not been checked against real alert emails yet.** The tests use
alerts written to match typical Pakistani bank wording. After your first sync,
look at **Settings → Skipped emails**. If a real alert appears there or is misread, see
[Fixing a parser](#fixing-a-parser).

## Monthly statements

Most banks email a monthly statement as a PDF attachment. For every enabled
bank or wallet, the app also searches for statement emails, which by default
come from the same sender, with "statement" in the subject and a PDF attached.
It then reads every transaction in the PDF.

- **How far back:** each sync covers the look-back period (**Home → Sync options**),
  a year by default. In the same place, *Read older statements* fetches any
  earlier year or set of months on request. It searches emails received from
  the start of the first month to about six weeks after the last, because a
  month's statement arrives after the month ends.
- **Passwords:** banks often lock e-statements, for example with your CNIC number
  or date of birth. Enter it per bank under **Accounts → Statement settings**. It's stored
  encrypted and only used to open that bank's statements. Statements that
  couldn't be opened are listed with the reason, and are tried again after you
  save a password.
- **Different sender or subject:** if a bank sends statements from another
  address or with another subject, set those per bank on the same page.
- **How PDFs are read** (`order_tracker/statements.py`): there's no template per
  bank. The app reads each word with its position on the page, and finds the
  header row (Date … Debit/Withdrawal … Credit/Deposit … Balance, or Date …
  Amount on card statements). Each amount below it goes to the nearest column.
  Lines starting with a date are transactions, and an indented line under one
  continues its description. Without a recognisable header, the running balance
  decides direction: down for money out, up for money in. Amounts need two
  decimals, so cheque and reference numbers aren't mistaken for amounts.
  Opening and closing balances and totals are skipped.

**This hasn't been checked against real statements yet.** The tests use PDFs
built to look like typical Pakistani bank and card statements. If one is
misread, see [Fixing a parser](#fixing-a-parser).

## Delivery services

| Service | Automatic (new orders) | Past history | Notes |
|---|---|---|---|
| Foodpanda | Gmail receipts | **Accounts → Import** (full history) | Email formats for Pakistan and Bangladesh, from the reference project. Orders without a restaurant name are counted as pandamart. |
| Careem | Gmail receipts | Gmail, plus CSV from careem.com → My rides → History → *Download a copy* | Careem emails a receipt after every ride to the email on your account. |
| inDrive | Gmail receipts | Only the receipts already in Gmail | No website, export or API. inDrive emails a receipt right after each trip **only if your inDrive profile has an email address**, so add it in the app now. |
| Krave Mart | Gmail receipts | Gmail | App-only. Parsed if Krave Mart emails you order confirmations. |

The Careem, inDrive and Krave Mart receipt parsers look for common total labels
("Total", "Trip cost", "Amount paid" and so on). They have not been checked
against real emails yet either.

### Fetching your full foodpanda history

foodpanda's website loads its *Orders* page from an order-history endpoint on
`fd-api.com`, authorized by your login token. **Accounts → Import → Foodpanda account**
calls the same endpoint:

1. Log in at foodpanda.pk (or foodpanda.com.bd) in Chrome or Edge.
2. Press F12, then go to **Application → Cookies** and select the foodpanda site.
3. Copy the value of the `token` cookie, paste it in, and click **Fetch order history**.

The token gives access to your foodpanda account until it expires, so treat it
like a password. The app uses it for that one fetch and never saves it.

This is **not an official API**. Two open-source tools use the same endpoint
([foodpanda-total](https://github.com/asdf93074/foodpanda-total),
[FoodpandaOrderHistoryTool](https://github.com/uWayLu/FoodpandaOrderHistoryTool)),
and the request shape here follows theirs. foodpanda can change or block it at
any time, and the app will then report the error.

### Importing CSV files

On **Accounts → Import**, upload a file of order history. If the file name contains the
service's name (for example `careem_rides.csv`), that service is picked
automatically. Check the guessed columns, then click Import. Re-importing the
same file adds nothing new.

## Setup

### 1. Install

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Python 3.11 or newer. For the phone app, also Node.js 20 or newer:

```bash
cd mobile && npm install
```

### 2. Register the app with Google (one time, by you)

Google requires every app that asks for Gmail permission to be registered. This
is the app's identity, which Google's consent screen shows to users. Users
never do this step; they just click *Continue with Google*.

1. In [Google Cloud Console](https://console.cloud.google.com/), create a project.
2. **APIs & Services → Library**: enable the **Gmail API**.
3. **OAuth consent screen** (*Google Auth Platform → Branding / Audience / Data access*):
   - User type *External*, app name, support email.
   - App home page: your app's URL. Privacy policy: `<your app URL>/privacy`.
   - Scopes: `openid`, `.../auth/userinfo.email`, `.../auth/userinfo.profile` and `.../auth/gmail.readonly`.
   - While testing, add every user's Gmail address under *Test users*.
4. **Credentials → Create credentials → OAuth client ID**: type *Web application*
   (the phone app uses it too, through the API), with these authorized redirect URIs:
   - `http://localhost:8000/auth/google/callback` for the API, or
     `<API_PUBLIC_URL>/auth/google/callback` once it has a public address;
   - `http://localhost:8501` if you also run the website.
5. Give the API the client ID and secret as environment variables:
   `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`. (If you've used the website,
   its **Set up Google access** page has already stored them encrypted in
   `data/google_client.enc`, and the API reads them from there.)

You don't need `secrets.toml`. Use it, or the environment variables (and
`GOOGLE_REDIRECT_URI` for the website), only if you'd rather not use the setup
page, for example on a hosting platform's secrets settings. See
`.streamlit/secrets.toml.example`.

### Letting other people sign in

`gmail.readonly` is one of Google's **restricted scopes**, which limits who can
use the app until Google has reviewed it:

| Publishing status | Who can sign in | Notes |
|---|---|---|
| **Testing** | Only the test users you list (up to 100) | Gmail permissions expire after 7 days, so users reconnect weekly. |
| **In production, unverified** | Anyone, up to 100 users in total | Users see an "unverified app" warning. |
| **In production, verified** | Anyone | Needs Google's app verification for restricted scopes, including an independent security assessment, renewed yearly. |

For yourself and a few friends, Testing or unverified production is fine. A
public launch needs verification. The Privacy page (`/privacy`) and the
explicit consent step are part of what Google reviews. Fill in `[app]
contact_email` so the Privacy page has a contact, and have the Privacy page
checked before you submit.

For a deployment:
- Use an HTTPS redirect URI, and set `API_PUBLIC_URL` to the API's public
  address (`https://api.example.com`); its callback is
  `<API_PUBLIC_URL>/auth/google/callback`.
- Set `[gmail] token_key` (or `GMAIL_TOKEN_KEY`) instead of relying on the key
  generated in `data/`.
- Complete the setup page yourself before sharing the address. Until a client
  is saved, whoever opens the app first sees that page.
- Each user's data lives in `data/users/`, so put it on persistent, backed-up
  storage.

### 3. Run the API

```bash
GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... .venv/bin/python -m api
```

It listens on port 8000 (`PORT` changes it); `--reload` restarts it when the
code changes. Its endpoints are listed at http://localhost:8000/api/docs, and the
privacy notice Google's review asks for is at http://localhost:8000/privacy.

### 4. Run the app

```bash
cd mobile
cp .env.example .env.local   # EXPO_PUBLIC_API_URL: where the API is
npm start
```

Then press `i` for the iOS simulator (on a Mac), `a` for an Android emulator, or
`w` for a browser. To use it on your own phone, install **Expo Go** from the App
Store or Play Store and scan the QR code; the API has to be reachable from the
phone, so see [Trying it on a phone](#trying-it-on-a-phone).

1. Read what the app will do, tick the box, and tap **Continue with Google**.
   Allow the read-only Gmail access on Google's screen.
2. On **Accounts → Banks & wallets**, add the banks and wallets you use.
3. Tap **Sync now** on **Home**. The first sync covers the last 365 days. The
   **Get started** card on Home walks through these steps until they're done.

### Trying it on a phone

Google only sends sign-ins back to `localhost` or to a public HTTPS address,
never to a computer's local network address. So:

- **iOS simulator, or the browser:** `http://localhost:8000` works as is.
- **Android emulator:** run `adb reverse tcp:8000 tcp:8000`, then
  `http://localhost:8000` works there too.
- **A real phone:** give the API a public HTTPS address, for example with a
  tunnel (`cloudflared tunnel --url http://localhost:8000`, or ngrok) or by
  deploying it. Set `API_PUBLIC_URL` to that address when starting the API, add
  `<that address>/auth/google/callback` to the OAuth client's redirect URIs, and
  put the address in `mobile/.env.local` as `EXPO_PUBLIC_API_URL`.

### Publishing the app

The app is built and signed in the cloud with [EAS](https://docs.expo.dev/eas/),
so no Mac or Android Studio is needed (an Apple Developer account is, for iOS):

```bash
cd mobile
npx eas-cli@latest login
npx eas-cli@latest build --profile preview --platform android   # an APK to install directly
npx eas-cli@latest build --profile production --platform all    # for the App Store and Play Store
npx eas-cli@latest submit --platform ios
```

Set `EXPO_PUBLIC_API_URL` for each build to the deployed API (in
`mobile/.env.production`, or as an EAS environment variable). Change the bundle
identifier and package name (`com.expensetracker.app` in `mobile/app.json`)
to your own first.

To deploy the API, run `python -m api` behind HTTPS (any host that runs Python;
a reverse proxy such as Caddy or nginx in front), as **one process**: syncs
are tracked in its memory. Set `API_PUBLIC_URL`, `GMAIL_TOKEN_KEY`, the Google
client, and:

| Variable | What it's for | Default |
|---|---|---|
| `APP_RETURN_PREFIXES` | Where sign-in may send the browser back to: the app's scheme, Expo Go while developing, the web build. | `expensetracker://,exp://,exps://,http://localhost:8081/` |
| `APP_WEB_ORIGINS` | Origins allowed to call the API from a browser (the web build). | `http://localhost:8081` |
| `ORDER_TRACKER_DATA_DIR` | Where each user's data lives: persistent, backed-up storage. | `data/` |

In production, drop `exp://,exps://` from `APP_RETURN_PREFIXES` once nobody uses
Expo Go, and add the web build's address to both if you host it.

### The website

The Streamlit website still works on the same data:

```bash
.venv/bin/streamlit run app.py
```

Open http://localhost:8501. The first time only, if the Google client isn't set
in the environment, its **Set up Google access** page asks for the client ID and
secret. Google opens in a new tab and the website continues there.

## Automatic background sync

The app (and the website) syncs by itself when a user opens it, if their last
sync was more than 6 hours ago. To keep everyone up to date even when the app is closed, run the
CLI on a schedule. It syncs every user who has granted Gmail access, each with
their own permission and their own banks and wallets:

```bash
.venv/bin/python -m order_tracker sync --days 30
```

For example, every 6 hours with cron (`crontab -e`):

```
0 */6 * * * cd /path/to/ExpenseReview && .venv/bin/python -m order_tracker sync --days 30 >> data/sync.log 2>&1
```

Other commands:

```bash
.venv/bin/python -m order_tracker sync --user you@gmail.com --sources meezan jazzcash careem --days 730
.venv/bin/python -m order_tracker sync --since 2023-01-01 --until 2024-02-15 --sources stmt:meezan
.venv/bin/python -m order_tracker export ledger.csv --user you@gmail.com
```

## Fixing a parser

- **Bank and wallet alerts**: `order_tracker/alerts.py`. Add the alert, with
  personal details removed, to `tests/test_alerts.py`, then adjust the patterns
  until it passes. For a bank whose emails are too different, narrow its sender
  or subject under **Accounts → Banks & wallets** first.
- **Statements**: `order_tracker/statements.py`. Add a PDF laid out like the
  misread one, with personal details removed, to `tests/statement_pdfs.py` and a
  test to `tests/test_statements.py`, then adjust the header words or row rules
  until it passes.
- **Delivery receipts**: one small class per service in `order_tracker/parsers/`
  (`sender_terms`, `total_labels`, `skip_subject_terms`, `describe()`), tested in
  `tests/test_parsers.py`.

Install the test tools with `.venv/bin/pip install -r requirements-dev.txt`, and
run the tests with `.venv/bin/python -m pytest` (the API's are in
`tests/test_api.py`). For the app, run `npm run typecheck` and `npm run lint` in
`mobile/`. Then use **Re-scan** in
**Home → Sync options** so stored emails are read again. Your category changes are kept.

## Project layout

```
mobile/                      The phone app (Expo, React Native, TypeScript); see mobile/README.md
  src/app/                   Screens, by route: sign-in, the four tabs, and sheets (payment, payments behind
                             a figure, add expense, sync options, a bank)
  src/sections/              One component per sub-tab
  src/components/            The app's look (cards, lists, fields), charts, icons, date picker
  src/lib/                   The API client, sign-in (PKCE), syncing, theme, response types
api/                         The API the app talks to (FastAPI); run with python -m api
  auth_routes.py             Continue with Google for the app: start, callback, one-time code exchange
  sync_jobs.py               Syncing in the background, with progress for the app to show
  home.py                    Home: status, syncing, Overview, Trends, Places, Budget, payments behind a figure
  payments.py                One payment (change it or remove it), adding an expense
  activity.py                Transactions (and CSV), statements, transfers, delivery orders
  accounts.py                Banks and wallets, statement settings, imports
  settings.py                Account and Gmail, rules and lists, skipped emails, privacy (also /privacy)
  common.py                  Signed-in user, their store, time zone, list rows
app.py                       The website (Streamlit): setup page, Continue with Google + callback, navigation
views/                       The four tabs (overview is Home, activity, accounts, settings), public privacy page
  common.py                  Signed-in user, store, formatting, the app's look (cards, colors, icons), charts
  components.py              Tappable list rows (st.components.v2), and redrawing on a theme switch
  dialogs.py                 Sheets: a payment, adding an expense, the payments behind a figure
  sections/                  One module per sub-tab, each with a render() function
order_tracker/
  users.py                   Signed-in users and their separate data directories
  sessions.py                Remembered sign-ins (30 days on the website, 180 in the app), stored as token hashes
  consent.py                 What users are told before allowing Gmail, and the privacy notice
  auth.py                    Continue with Google (identity + Gmail permission), revoking, encrypted tokens
  config.py                  Google client (setup page, secrets or env), data dir, encryption key
  gmail_client.py            Gmail API: search and fetch messages
  email_utils.py             MIME walking, HTML to text
  institutions.py            Bank/wallet presets and their Gmail searches
  alerts.py                  Bank/wallet alert parser, also for pasted SMS and notifications
  statements.py              Monthly statement emails and PDF statement reader
  crypto.py                  Encrypts statement passwords at rest
  categories.py              Built-in category keywords
  rules.py                   The user's own rules: category and who it was for
  budgets.py                 Monthly budgets and limits, and how a month is going against them
  insights.py                What stands out: limits, places and categories above usual, habits
  money.py                   Writing amounts: Rs 3,119, Rs 2.53 lakh
  parsers/                   Delivery receipt parsers
  foodpanda_account.py       Full order history from a foodpanda account (unofficial endpoint)
  importers.py               CSV import with column guessing
  sync.py                    Incremental sync: search, parse, store, then reconcile
  reconcile.py               Payment ↔ order links and internal transfers
  ledger.py                  The combined money in / money out list; rules, edits and what counts
  storage.py                 SQLite: orders, transactions (incl. ones you add), statements, banks, edits, rules,
                             budgets, processed emails
  __main__.py                CLI (sync, export)
tests/                       pytest suite
```

## Limitations

- Only money movements that reach your Gmail are found automatically. SMS-only alerts and in-app-only history are invisible to the app, so turn on email alerts where you can; monthly statements fill in the rest for banks that email them, and you can paste an SMS or notification under **Add expense**. Reading bank SMS or notifications by itself would be a next step for the phone app, on Android only: iPhones don't let apps read other apps' notifications or SMS.
- Statements must be text PDFs. Scanned (image-only) PDFs, and statements sent as ZIP files or links to a website, can't be read.
- If a bank emails two alerts for one payment (say, a card alert and an account alert), both are counted. Narrow that bank's subject under **Accounts → Banks & wallets** to keep only one kind.
- Totals are not converted between currencies. With several currencies (PKR and USD, say), pick one in the currency filter.
- The API keeps track of running syncs in memory, so run it as one process.
- Users are kept apart by directory on one server. Anyone with access to that server can read every user's data. The Gmail tokens are encrypted, but the extracted transactions are not.
# ExpenseTracker
