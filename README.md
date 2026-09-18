# Journal club

This repository runs the lab's journal club website and its announcements. People sign up and contribute through one Google Form. A GitHub workflow reads the form's Google Sheet every three hours, builds the site on GitHub Pages, and posts announcements to Mattermost.

The design is written up in Max's vault: [2026-09-17_journal-club-redesign-design.md](obsidian://open?vault=FINALOBSIDIAN&file=02_Areas%2Fjournal-club%2F2026-09-17_journal-club-redesign-design), at `02_Areas/journal-club/` in the vault.

Day-to-day running, including what to do when something breaks, is in [RUNBOOK.md](RUNBOOK.md). This README is for setting the club up.

## What is where

| Path | Holds |
|---|---|
| `sync/` | Reads the sheet, places claims, copies explainers, posts to Mattermost |
| `web/` | Builds the site: templates, stylesheet, and the explainer starter template |
| `content/guide.md` | The presenter guide, shown on the site at `/guide/` |
| `data/` | What the workflow commits: page addresses, schedule, archive, announcement log |
| `explainers/` | Approved explainers, stored as text so they never run on the site's own origin |
| `.github/workflows/sync.yml` | The workflow |
| `tests/` | The test suite, which runs offline |

## Setting it up

Do these in order. Exact spelling matters throughout. The sync finds everything in the sheet by name: tabs by their names, columns by their headers, and answers by their text. A misspelling never raises an error. What it does instead depends on where it is:

- **A misspelt option, or a misspelt `Timestamp`, `Action`, `Session`, `Name`, `Format`, `Takeaway` or `Part` title.** The sync skips every row it affects, and reports each one in Mattermost.
- **A misspelt `DOI`, `Text`, `Link` or `Why` title.** The row is kept, that answer is silently dropped, and nothing is reported. The exception is the `DOI` in "I'd come to this", the section's only answer: without it the row is skipped and reported.
- **A misspelt `hide`, `status` or `checked by` header.** That column is silently ignored. Without `hide`, nothing can be hidden. Without `status`, nothing that needs approval is ever published. Without `checked by`, no author reply is.

### 1. The Google Form

Google writes each question's title as its column header in the sheet. So the question **titles** below are what the sync reads. Put any longer wording in the question's description, not its title.

The site's buttons open the form with some answers already filled in. A prefilled link selects a multiple-choice option only when its text matches the option exactly. Type every option below exactly as given, capitals included.

**Form settings**

- Do not collect email addresses.
- Do not require sign-in, and add no file-upload question. A file-upload question makes Google require sign-in for the whole form, which slows the takeaway QR code for everyone.
- In the form's description, say that everything submitted is published on the club's public site under the name given. Say too that hiding something later removes it from the site, but not from the repository's history once it is there. Most contributions enter that history after seven days. The name on a claim, and an approved explainer file, enter it at the next run.
- A suitable confirmation message: "Thank you. Most contributions appear on the site within about three hours. A discussion synthesis, what it means for our work, a slides link, an explainer link or an author reply appears once an organiser has approved it. A claim is confirmed once it appears on the site and in Mattermost."

**Section 1, seen by everyone**

| Title | Type | Options, exactly | Notes |
|---|---|---|---|
| `Action` | Multiple choice, required | `Claim a session`, `Add a takeaway`, `Suggest a paper`, `I'd come to this`, `Add to a page` | Turn on "Go to section based on answer". Put "What do you want to do?" in its description. |
| `Session` | Short answer, not required | | Description: "Filled in for you when you come from the site. Otherwise the session's date, as YYYY-MM-DD, or the end of its page's address." |

`I'd come to this` takes a straight apostrophe, `'`. A curly one, which some keyboards and editors insert, makes a different option, and the sync skips every row that uses it.

`Session` sits in the first section because the site fills in one question for three actions: claiming a session, adding a takeaway and adding to a page. A question has only one prefill id, so it cannot be repeated in each section.

Branch each answer of `Action` to its own section, below. Set every one of those sections to go to "Submit form" when it ends.

**Section "Claim a session"**

| Title | Type | Options, exactly | Notes |
|---|---|---|---|
| `Name` | Short answer, required | | |
| `Format` | Multiple choice, required | `Help me read this`, `Full presentation`, `Short slot on one figure` | |
| `DOI` | Short answer | | |
| `Text` | Short answer | | Description: "The paper's title, if it has no DOI." |
| `Link` | Short answer | | Description: "A link to the paper, if it has no DOI." |

**Section "Add a takeaway"**

| Title | Type | Notes |
|---|---|---|
| `Name` | Short answer, required | |
| `Takeaway` | Paragraph, required | Description: "What became clearer, changed your mind, or is still unresolved?" |

**Section "Suggest a paper"**

| Title | Type | Notes |
|---|---|---|
| `Name` | Short answer, required | |
| `DOI` | Short answer | |
| `Text` | Short answer | Description: "The paper's title, if it has no DOI." |
| `Link` | Short answer | |
| `Why` | Paragraph | Optional. Shown on the wishlist. |

**Section "I'd come to this"**

| Title | Type | Notes |
|---|---|---|
| `DOI` | Short answer, required | Description: "Filled in for you by the wishlist's I'd come button." It may hold a DOI or a link, and both work. |

The sync counts these answers and reads nothing else from this section. A name question here would collect names it never uses.

**Section "Add to a page"**

| Title | Type | Options, exactly | Notes |
|---|---|---|---|
| `Part` | Multiple choice, required | `Discussion synthesis`, `What it means for our work`, `Slides link`, `Explainer link`, `What happened next`, `Author reply` | |
| `Text` | Paragraph | | |
| `Link` | Short answer | | Description: "For slides or an explainer: the link. An explainer on Google Drive needs sharing set to Anyone with the link." |
| `Name` | Short answer, required | | |

Several titles, such as `Name`, `DOI`, `Text` and `Link`, repeat across sections. That is expected. The sheet gets one column per question, and the sync takes the filled-in cell under each title.

### 2. The Google Sheet

1. In the form's Responses view, choose **Link to Sheets** and create a new spreadsheet.
2. Rename the tab the form created, such as "Form responses 1", to exactly `Responses`.
3. Check that its first column is headed `Timestamp`. If your Google account is not in English, Google may have written it in your language. If so, change the header to `Timestamp`, then submit a test response and check that it lands under that header.
4. To the right of the form's columns, add three columns headed `hide`, `status` and `checked by`. Organisers type in these. The `hide` column can be made into checkboxes.
5. Set the spreadsheet's time zone to Amsterdam, under **File**, **Settings**, **Time zone**. The sync reads every date and timestamp as a raw serial number, which counts days in the spreadsheet's own time zone, and then treats it as Amsterdam time. The sheet's locale does not matter.
6. Add these tabs, each with this header row in row 1. Tab names must match exactly, capitals included. In headers, capitals do not matter but spelling does.

| Tab | Header row | Edited by |
|---|---|---|
| `Settings` | `key`, `value` | Max |
| `Open sessions` | `date`, `title`, `guest`, `affiliation`, `doi`, `length_minutes` | Max |
| `Skipped weeks` | `date` | Max or the co-organiser |
| `Session status` | `date`, `status` | Max or the backup host |
| `Aliases` | `alias`, `display name` | Anyone |

Only `Settings` must be filled in. Two mistakes stop every run, announcements included. One is a missing or broken `Settings` tab. The other is an `Aliases` tab whose `alias` or `display name` header is misspelt, and anyone may edit that tab. A missing `Responses` tab is reported in Mattermost. Any other tab may stay empty, but a misnamed one also reads as empty, with no warning.

**The Settings tab**, one key per row. Every key is required except `entry_paper`.

| key | Example value | What it does |
|---|---|---|
| `club_name` | `NCL Journal Club` | Shown on every page |
| `first_session` | `2026-09-30` | The first session's date. It should be a Wednesday; sessions repeat every 14 days from it. |
| `session_hour` | `11` | Start time, hour, 24-hour clock |
| `session_minute` | `0` | Start time, minutes |
| `room` | `Lab room` | Shown on the site and in announcements |
| `horizon_days` | `183` | How far ahead the schedule runs, so how far ahead a session can be claimed. 183 is about six months. |
| `site_base_url` | `https://<account>.github.io/<repository>` | The site's address, used in announcement links |
| `form_url` | `https://docs.google.com/forms/d/e/<form id>/viewform` | The form's public address |
| `entry_action` | `entry.1234567890` | The prefill id of `Action`; see step 3 |
| `entry_page` | `entry.2345678901` | The prefill id of `Session` |
| `entry_paper` | `entry.3456789012` | Optional. The prefill id of the `DOI` question in "I'd come to this". Without it the wishlist shows no "I'd come" button. |

**The other tabs**

- Dates in `Open sessions`, `Skipped weeks` and `Session status` must fall on a regular session date: every other Wednesday from `first_session`. The sync ignores any other date without a warning.
- `Open sessions`: an open session takes the place of the regular session on its date, and cannot be claimed. `length_minutes` is a whole number; a blank means 60. The `doi` is optional; with one, the page shows the paper's title and authors.
- `Session status`: `status` is `cancelled` or `held`. Mark a session `held` only when it happened but nobody added a takeaway, since a takeaway already marks it held.
- `Aliases`: maps a name variant to the name shown on the site. The match ignores capitals.

**Sharing:** lab members and the co-organiser as editors. The service account from step 4 as a viewer.

### 3. Prefill ids

The site builds its form links from three prefill ids.

1. In the form, open the menu and choose **Get pre-filled link**.
2. In section 1, choose `I'd come to this` for `Action`, and type `2026-01-07` in `Session`. Press **Next**.
3. Type `10.1000/test` in `DOI`, then press **Get link** and copy it.

The link holds pairs like `entry.1234567890=...`. The one holding the words of the action is `entry_action`. The one holding the date is `entry_page`, and the one holding the DOI is `entry_paper`. Copy each `entry.` name, including the word `entry.`, into the Settings tab. The part of the link before `?` is `form_url`.

To check, open any session page on the site once it is running, and press **Add a takeaway**. The form should open with `Add a takeaway` chosen and the page filled in.

### 4. The service account

The workflow reads the sheet as a Google service account, and only ever reads it.

1. In the Google Cloud console, create a project, and enable the **Google Sheets API**. The sync opens the sheet by its id, which needs no other API.
2. Create a service account, and add a key of type JSON. Download the key file.
3. Share the sheet with the service account's email address, shown as `client_email` in the key file, as a **Viewer**.

The whole content of the key file becomes the secret `GOOGLE_SERVICE_ACCOUNT_JSON`. The sheet's id, the long string in its address between `/d/` and `/edit`, becomes `SHEET_ID`.

### 5. Mattermost

A Mattermost system administrator must enable incoming webhooks in the System Console, under **Integrations**. Without that, nothing can be posted.

Then create an incoming webhook for the club's channel. Its address becomes the secret `MATTERMOST_WEBHOOK_URL`.

Without this secret, the workflow prints each message in the run's log instead of posting it. It still records the message as sent, so it is not posted later when the webhook is added.

### 6. The monitor

The monitor notices when runs stop. A workflow cannot report a run that never started.

1. Create a check at a ping-monitoring service. Healthchecks.io is the candidate the design names.
2. Give it a period of three hours, and a grace period long enough for GitHub's delays. Those delays can reach an hour or more.
3. Send its alerts to the Mattermost channel if the service can. Otherwise send them by email to Max and the co-organiser.

The check's ping address becomes the secret `MONITOR_PING_URL`. The workflow pings it at the end of every run, including failed runs, so the monitor alerts only when runs stop. A failed run is reported in Mattermost instead. A missing or failing ping never fails the run.

### 7. The GitHub repository

1. Make the repository public, on Max's account. The site's address is then `https://<account>.github.io/<repository>/`, which is `site_base_url` in Settings.
2. Under **Settings**, **Pages**, set the source to **GitHub Actions**.
3. Under **Settings**, **Secrets and variables**, **Actions**, add the four repository secrets below.
4. Give the co-organiser write access.
5. Leave the branch the workflow runs on open to pushes from Actions. Each run commits and pushes to it.

| Secret | Holds | Used by the steps |
|---|---|---|
| `SHEET_ID` | The sheet's id | Sync, Build, Announce |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | The whole service-account key file | Sync, Build, Announce |
| `MATTERMOST_WEBHOOK_URL` | The incoming webhook's address | Sync, Announce, Report failure |
| `MONITOR_PING_URL` | The monitor's ping address | Ping the monitor |

Only Max, as the owner, can change these secrets. The runbook's manual mode covers the time until he can.

### 8. First run and checks

Run these checks on one clearly marked test session: the last one listed under "Upcoming" on the front page, the furthest ahead. Give every test submission the name `Test`, and start its text with `TEST`.

Hide every test row on the day you make it, approved ones included. Anything left unhidden for seven days enters the public repository's history, and stays there for good.

1. Open the **Actions** tab, choose **sync**, and press **Run workflow**.
2. Open the site. The front page should list the upcoming sessions, and the menu should include **Guide**.
3. On the test session's page, add a test takeaway with its button. Run the workflow, and check that the takeaway appears.
4. On the same page, submit a test discussion synthesis with **Add to this page**. Check that it does not appear until its row's `status` says `approved`, and that it does appear after.
5. Share `web/explainer-template.html` on Google Drive with "Anyone with the link". Submit it on the test page as an explainer link, approve it, run the workflow, and check that it appears.
6. Hide all three test rows. Run the workflow once more, and check that the test page is plain again.

The explainer file enters the repository's history at the run that copies it, and hiding its row does not remove it from there. That is harmless for the template, which is public anyway.

The design's section 8 lists the remaining launch checks.

## Running it locally

You need Python 3.12 or newer. On Windows, use `py -3.12` wherever this says `python`.

```
python -m pip install -e ".[dev]"
python -m pytest
```

The tests run offline. They never touch the sheet, git or Mattermost.

If a pytest plugin installed outside this project breaks test collection, switch it off with `-p no:<plugin>`. Max's machine needs `-p no:nengo`, for example.

The three commands are the workflow's steps:

| Command | What it does |
|---|---|
| `python -m sync.cli sync` | Reads the sheet, writes `data/`, copies explainers, posts notices |
| `python -m sync.cli build` | Reads the sheet and `data/`, and writes the site to `_site/` |
| `python -m sync.cli announce` | Posts the announcements that are due |

All three read the real sheet, so they need `SHEET_ID` and `GOOGLE_SERVICE_ACCOUNT_JSON`. The second holds the key file's content, not its path. In PowerShell:

```
$env:SHEET_ID = "<the sheet's id>"
$env:GOOGLE_SERVICE_ACCOUNT_JSON = Get-Content path\to\key.json -Raw
python -m sync.cli build
python -m http.server 8000 -d _site
```

Then open `http://localhost:8000/`. Serve the site like this rather than opening its files from disk: from disk, links to folders and the explainer frame do not work. Pull first, because `build` reads `data/` from your checkout.

**`build` is safe.** It writes only `_site/`.

**`sync` and `announce` act for real.** Before posting each message, they commit `data/announcements.json` and push it to the repository. With `MATTERMOST_WEBHOOK_URL` set, they really post to the channel. Without it, they print the messages instead, but still record them as sent and push the log, so the workflow will never post them. `sync` also rewrites `data/` and `explainers/` in your checkout. Run these two locally only when you mean to do the workflow's job by hand.
