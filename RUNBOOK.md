# Runbook

This is how the journal club keeps running when Max is away. It has four parts:

1. What runs by itself.
2. The backup host, who runs a session when Max is away.
3. What the co-organiser can repair.
4. Manual mode, for when only Max can fix the automation.

Setup is in `README.md`. You do not need it to use this runbook.

## People

| Role | Name |
|---|---|
| Lead | Max |
| Co-organiser | **[BLANK: Max fills in]** |
| Backup host | **[BLANK: Max fills in]** |

| Place | Address |
|---|---|
| The site | **[BLANK: Max fills in]** |
| The sheet | **[BLANK: Max fills in]** |
| Mattermost channel | **[BLANK: Max fills in]** |

## Human duties

Everything else runs by itself. Each of these has two people, so no duty rests on one.

| Duty | Lead | Backup |
|---|---|---|
| Chair a session, and invite people personally | Max | Backup host |
| Host when Max is away, including the empty-room fallback | Backup host | Co-organiser |
| Approve a synthesis, explainer or author reply | Max | Co-organiser |
| Mark a session cancelled | Max | Backup host |
| Act on a missed-announcement alert | Backup host | Co-organiser |
| Repair the site or the workflow | Co-organiser | Max |
| Change stored credentials | Max | Nobody, so part 4 exists |
| Quarterly review | Max | Co-organiser |

---

## 1. What runs by itself

### When it runs

A GitHub workflow called **sync** runs every three hours, and whenever someone starts it by hand. In Amsterdam time it starts at:

- Summer time: 02:17, 05:17, 08:17, 11:17, 14:17, 17:17, 20:17, 23:17.
- Winter time: 01:17, 04:17, 07:17, 10:17, 13:17, 16:17, 19:17, 22:17.

GitHub often starts scheduled runs late, sometimes by an hour or more, and occasionally drops one.

### What each run does, in order

1. Reads the sheet. Hidden rows are dropped.
2. Places claims, earliest first, and gives each new page its address.
3. Looks up paper details for new DOIs.
4. Copies approved explainers whose link is new.
5. Posts notices to Mattermost: a claim that was not placed, contributions waiting for approval, new problems in the sheet, and explainers that could not be copied.
6. Commits the archive to the repository.
7. Builds the site and publishes it.
8. Posts any announcement that is due. This step runs even when an earlier step failed.
9. Pings the monitor. This also happens on every run, failed or not.
10. If any step failed, posts "Journal club sync failed" to Mattermost, with a link to the run.

### Announcements

| Message | Posted by the first run after | Only if |
|---|---|---|
| Who claimed which session | the claim is submitted | the session has not started |
| Open paper chat, with a claim link | 09:00 on the Friday before | nobody has claimed a regular session |
| Who presents what | 09:00 on the Monday before | the session is not cancelled |
| A short reminder | 08:00 on the day | the session is not cancelled |

In practice, Friday's and Monday's messages come at about 11:17 in summer and 10:17 in winter. The reminder comes at about 08:17 in summer, but not before 10:17 in winter. A late run can miss the reminder altogether, because nothing is posted once a session has started.

Three rules hold for every message:

- **Nothing is posted twice.** Each message is written to the announcement log, `data/announcements.json`, and committed before it is posted. The log cannot know about a message someone posted by hand until it is recorded there, as in part 3.
- **Only the newest is posted.** If several messages for one session are overdue, only the newest goes out. The rest are logged as skipped.
- **No message for a session that cannot happen.** Nothing is announced for a cancelled session, a skipped week, or a session that has already started.

### The archive

- Each run commits `data/` and `explainers/` to the repository when anything changed.
- Takeaways and other contributions enter the archive, `data/submissions.json`, only once they are seven days old. Until then they live only in the sheet and on the site.
- Claims enter the repository at the first run. So do explainer files, as soon as they are copied.
- The first run of each month commits a small change to `data/sync_state.json`. It exists to stop GitHub disabling the schedule after 60 days without activity.

### The monitor

The monitor is pinged at the end of every run, even a failed one. So it alerts only when runs stop happening. A run that fails is reported in Mattermost instead.

---

## 2. The backup host

You run a session when Max is away. The room still belongs to the presenter. Your part is to open the room, keep it welcoming, and make sure the page gets its takeaways.

**Before the session**

- Look for Monday's announcement in the Mattermost channel. It says who presents what, or that it is an open paper chat. The front page of the site says the same under "Up next".
- A cancelled session or a skipped week has no Monday message. Otherwise, if Monday's message has not appeared by Monday evening, post it yourself from the templates in part 4. The automation is probably down.
- If the monitor sends an alert, runs have stopped. Check the channel the same way, and post what is missing.
- Whenever you post a message by hand, tell the co-organiser exactly what you posted and for which session. They record it in the repository, so the automation does not post it a second time when it restarts. That recording is theirs to do, not yours.

**On the day**

- The reminder normally arrives in the morning.
- Open the session page on the room's screen. The front page links to it under "Up next". When someone has claimed the session, Monday's announcement links to it too. An open paper chat's announcement has no link.
- Start on time. Introduce the presenter, then hand the room to them.
- With two short slots, keep each to about ten minutes plus discussion.
- Near the end, show the QR code at the bottom of the session page. Ask the room: "What became clearer, changed your mind, or is still unresolved?" Scanning the code opens the takeaway form for that page.
- For the club's first four sessions, ask one or two newcomers afterwards whether there was a point where they felt able to join in. Tell Max what they said.

**If nobody brings anything**

- Open the wishlist page on the site. Take the paper the most people said they would come to. If no paper has any, take any one.
- Put one figure from it on screen and look at it together. What are the axes? What does the paper claim it shows? Does the room believe it?
- That is a session. The QR code on the page works as usual.

**Afterwards**

- If people added takeaways, nothing else is needed. The session counts as held.
- If it happened but nobody added a takeaway, add a row to the sheet's **Session status** tab: the date, and `held`.
- If it could not happen, add the date and `cancelled` to **Session status**, and say so in the channel. If someone had claimed it, Mattermost then tells them their claim "was not placed" and links the next open session. That is expected.

---

## 3. What the co-organiser can repair

You need edit access to the sheet and write access to the GitHub repository. Anything you change takes effect at the next run. To see it sooner, run the workflow by hand.

### Approve a pending contribution

Mattermost posts "contributions are waiting for approval in the sheet", with the part, the page and the name.

1. In the **Responses** tab, find the row: action "Add to a page", the page in **Session**, the part in **Part**.
2. Check that it came from the presenter, or that the presenter agreed to it. For an explainer, also open the link and check that the file works.
3. Type `approved` in the row's **status** column. Any other word leaves it waiting.

It appears at the next run. A newer approved version of the same part replaces the older one on the page.

These parts wait for approval: discussion synthesis, what it means for our work, slides link, explainer link and author reply. Takeaways, what happened next, wishlist entries and claims never wait.

### Approve an author reply

An author reply needs two things: `approved` in **status**, and a note in **checked by**. Without both it stays off the site and out of the archive.

1. Confirm that the reply really came from the author, and that they agree to its publication. The simplest way is through the presenter, who emailed the author: ask the author to confirm in that thread.
2. In **checked by**, write who checked and how. For example: `Max, confirmed by email with the author, 3 Nov 2026`.
3. Type `approved` in **status**.

### Decline or withdraw something

Hide its row, as below. A declined item left unhidden stays on the approval list. If you hide an approved item that replaced an older approved one, the page shows the older one again.

### Hide a row

In the **Responses** tab, put one of these in the **hide** column: `yes`, `y`, `x`, `true`, `1` or `hide`. A ticked checkbox also works.

- To show the row again, clear the cell, or type `no`, `false` or `0`.
- Any other value also hides the row, and Mattermost reports it as a problem.
- The row leaves the site at the next run.
- Hiding a claim releases the session, so someone else can claim it.
- Hiding cannot remove what is already in the repository's history. That is any contribution older than seven days, the name and time of every claim, and every explainer file that was copied.

### Fix a sheet problem

Mattermost posts "The sheet has a new problem", saying what is wrong, usually with the tab and row. Each problem is posted once. The row is skipped until you fix it or hide it.

- Type dates as `YYYY-MM-DD`.
- Action, format and part cells must hold one of the form's options as the form wrote them.
- **Session status** takes only `cancelled` or `held`.
- Dates in **Open sessions**, **Skipped weeks** and **Session status** must be regular session dates, every other Wednesday from the first session. Any other date is ignored, with no warning.
- To show two spellings of a name as one person, add a row to **Aliases**: the variant under **alias**, and the name to show under **display name**.

If every run fails, check the **Settings** tab and the **Aliases** header row first. A missing or broken Settings value stops the whole run, announcements included. So does an Aliases tab whose `alias` or `display name` header is misspelt. The run's log names the tab, and the key or column.

### Record a message posted by hand

The workflow does not know about messages posted by hand. When it next runs, it can post the same message again. So record each hand-posted message in the announcement log **before** you run the workflow by hand or re-enable its schedule.

This is a repository edit, for the co-organiser or Max. The backup host only tells you what they posted.

1. In the repository on GitHub, open `data/announcements.json` and edit it.
2. Add one entry for each message posted by hand, with the state `sent`. For Monday's message about 14 October:

   ```
   "2026-10-14:monday": {"at": "2026-10-12T19:30:00+02:00", "state": "sent"},
   ```

3. Commit directly to the default branch.

The file is JSON, so every entry except the last ends with a comma. Only the entry's name is checked, so any time will do for `at`.

| Message posted by hand | Entry name |
|---|---|
| Friday's, Monday's or Wednesday's announcement | `<date>:friday`, `<date>:monday` or `<date>:wednesday` |
| A claim confirmation | `<page>:claim` |
| A "not placed" notice | `reject:<time>\|<name>` |

- `<date>` is the session's date, written `2026-10-14`.
- `<page>` is the page the claim will get: the first address for that date not yet used in `data/slots.json`. For a whole-session claim that is `<date>`, then `<date>-2`, then `<date>-3`. For a short slot it is `<date>-a`, then `<date>-b`. Two claims for one date take them in the order of their Timestamp.
- `<time>` is the claim's **Timestamp** from the Responses tab, written like `2026-10-01T10:00:00+02:00`. That is Amsterdam time to the second, ending `+02:00` in summer time and `+01:00` in winter time.
- `<name>` is the claim's **Name**, exactly as it was typed in the form.

A message posted by hand for a stuck `sending` entry needs no record, because its entry already blocks a repeat.

If runs restart by themselves before a message is recorded, it can still be posted twice. So record it as soon as you hear of it.

### Run the workflow now

1. If anyone posted a message by hand since the last successful run, record it first, as above.
2. In the repository on GitHub, open the **Actions** tab.
3. Choose **sync** on the left.
4. Press **Run workflow**, then **Run workflow** again.

It takes a few minutes. Runs queue rather than overlap, and the workflow never posts a message it has already logged.

### Re-enable a schedule GitHub disabled

GitHub disables a public repository's scheduled workflows after 60 days without activity. The monthly keep-alive commit should prevent that. If it happens anyway:

1. Record every message posted by hand while runs were stopped, as above. Do this first.
2. Open the **Actions** tab and choose **sync**.
3. A banner says the workflow is disabled. Press **Enable workflow**.
4. Run the workflow once by hand.

The signs are an Actions list with no new runs for several hours, and an alert from the monitor.

### A log entry stuck at `sending`

Every message is written to `data/announcements.json` as `sending`, and committed, before it is posted. Once posted, it becomes `sent`. An entry left at `sending` after a run has finished means the post was attempted but never confirmed. The run died while posting, or Mattermost returned an error. The message may be in the channel, or it may not.

To find one, open `data/announcements.json` in the repository on GitHub and search the page for `sending`. The entry's name says which message it was.

| Entry name | Message | Search the channel for |
|---|---|---|
| `<date>:friday`, `<date>:monday`, `<date>:wednesday` | That announcement for the session on that date | The date, such as "14 October" |
| `<page>:claim` | The confirmation of a claim | The date, such as "14 October" |
| `reject:<time>\|<name>` | The "not placed" notice for that person's claim | The person's name |
| `pending:<count>:<time>` | The list of contributions waiting for approval | "waiting for approval" |
| `problem:<code>` | A report of a problem in the sheet | "The sheet has" |
| `explainer-failed:<page>:<code>` | The notice that a page's explainer was not published | "The explainer for page" |

Webhook posts appear under the webhook's name, not a person's. So search the channel rather than scrolling for a familiar name.

1. Search the channel for the message, as the table says.
2. If it is there, nothing more is needed.
3. Never edit or delete the entry to make the system post it again. The system will never retry it, by design.
4. If it is missing, what to do depends on the message.

- **An announcement or a claim confirmation.** If the session has already started, post nothing: the message no longer helps, and the session page still exists. Otherwise post it once by hand from the templates in part 4. It never reached the channel, so this does not duplicate it. Post an announcement only while it is still the newest one due for that session. Friday's is out of date once someone claims the session, or once Monday 09:00 has passed. Monday's is out of date from Wednesday 08:00.
- **A "not placed" notice.** Tell the person by hand, from the template in part 4.
- **The approval list.** Post nothing. Look in the Responses tab for rows still waiting, and approve or hide them.
- **A problem report.** Post nothing. The entry holds only a fingerprint of the problem, not its text, so look over the sheet's newest rows for the mistake.
- **An explainer notice.** Post nothing. Open the page. If it shows no explainer, the copy is still failing, usually because the file's sharing is not set to "Anyone with the link". Tell the presenter.

### Refresh an explainer

The sync copies an explainer again only when its approved link changes. If a presenter changed the file behind the same link:

1. In the repository on GitHub, open `explainers/<page>/explainer.txt`, where `<page>` is the page's address, such as `2026-10-14`.
2. Delete the file, and commit directly to the default branch.
3. Run the workflow. It copies the file again from its approved link.

If the copy fails, the page shows no explainer until it succeeds, and Mattermost says why. Older versions stay in the repository's history.

### When a run fails

Mattermost posts "Journal club sync failed", with a link to the run. Open the link. The step marked in red is the one that broke.

| Failed step | Usual cause | What to do |
|---|---|---|
| Sync or Build | The sheet, most often the Settings tab or the Aliases header row | Fix it, then run the workflow again |
| Commit the archive | Someone pushed at the same moment | Run the workflow again |
| Announce | Mattermost could not be reached | Check for a `sending` entry, above |

The monitor ping never fails a run.

If a run keeps failing and its log mentions credentials, permission, or an error 401 or 403, only Max can fix it. Switch to manual mode.

---

## 4. Manual mode

Use this when the automation is broken in a way only Max can fix, such as an expired credential, and Max is away. The club keeps running with no automation at all.

**The sheet is the schedule.**

- Sessions are every other Wednesday from `first_session` in the **Settings** tab, at the time and in the room given there.
- Leave out the dates in **Skipped weeks**, and the sessions marked `cancelled` in **Session status**.
- The **Open sessions** tab lists guest sessions. They cannot be claimed.

**Place claims by hand.**

- Claims still arrive in the **Responses** tab. Read them in order of **Timestamp**.
- For each session, the earliest claim wins. A session holds one "Help me read this" or "Full presentation", or up to two "Short slot on one figure".
- Tell each claimant in the channel whether they got the session, from the templates below.

**Keep a list of every message you post by hand**, with its session and its claimant if it has one. Before the automation runs again, the co-organiser or Max records each one in the repository, as in part 3, "Record a message posted by hand".

**The site stays up but stops updating.** The QR code on a session's page still opens the form, and the sheet keeps every takeaway until the automation is back.

**Post the announcements by hand**, at the usual times, from these templates. Fill in the brackets. The format is written as "help me read this", "presentation" or "one figure".

Friday before, only if nobody has claimed the session:

```
No one has claimed [14 October] yet, so it is an open paper chat: bring anything you read, no slides. [14 October 11:00, room]. Claim it instead: [site address]
```

Monday before:

```
This Wednesday, [14 October 11:00, room]. [Name] on [paper title] ([format]).
```

or, for an open paper chat:

```
This Wednesday, [14 October 11:00, room]. Open paper chat: bring anything you read, no slides.
```

Wednesday morning:

```
Today, [14 October 11:00, room]. [Name] on [paper title] ([format]).
```

or, for an open paper chat:

```
Today, [14 October 11:00, room]. Open paper chat: bring anything you read, no slides.
```

When you place a claim by hand:

```
[Name] claimed Wednesday [14 October] ([format]).
```

When a claim does not fit:

```
[Name]: your claim for [14 October] was not placed, because that session is already taken. The next open session is [28 October].
```

### Leaving manual mode

The first run after the repair posts the newest due message for each upcoming session. It also posts a confirmation for every claim that arrived while the automation was down and whose session is still ahead, and a "not placed" notice for every claim that did not fit. None of these know about the messages posted by hand.

So before that run, the co-organiser or Max records every message on the list, as in part 3, "Record a message posted by hand". Only then run the workflow.
