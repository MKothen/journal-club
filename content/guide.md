# Presenter guide

Everything here is optional. Take what helps and leave the rest.

The room belongs to whoever presents. You choose the paper, the format and how the hour goes.

Every session gets a page on this site. A paper, one open question and a couple of takeaways from the room make a finished page. Anything more is your choice.

## Help me read this

Bring a paper you are stuck on. It can be one from your own project, or one you keep meaning to understand.

Say what you understood and where you got stuck. Then the room works through it with you. Nobody expects you to be the expert, and you do not need to become one first.

This format also changes what the most experienced people in the room do. Instead of carrying the discussion, they help you through the paper.

Some things that help:

- Say early which part lost you: a method, a figure, or a step in the argument.
- Put the figure you are stuck on up on the screen.
- Ask your question out loud, and let the room take it from there.

To claim a session, press "Claim this" next to an open session on the front page, and choose "Help me read this". Your claim is confirmed once it appears on the site and in Mattermost, usually within three hours.

## The start-here slide

If you want a way in, your opening slide can carry three headings:

- **The question.** What is the paper trying to establish?
- **The evidence.** Which figure or result should we understand first?
- **The uncertainty.** What should the room help resolve?

It suits a computational paper well. "What did you think?" is a hard way into a model. "Here is what the model receives, what it predicts, and the result that separates this mechanism from the alternative" is an easy one.

This slide is optional. Adapt it or skip it. For now it lives on a slide only, not on the session page.

## Presenting to a room that has not read the paper

Most people in the room will not have read the paper. That is expected, and they are welcome anyway. The aim is to bring them to a point where they can join in.

What tends to work:

- Lead with the question the paper asks, not with the background.
- Put one figure on the screen and stay there.
- Say what the axes are and what each panel shows.
- Say what the figure would look like if the claim were wrong.
- Before you explain a figure, ask the room what they see.
- Define a term when you first need it, rather than in a glossary at the start.
- Say what you are unsure about. It makes it easier for others to say the same.

## A one-figure slot

Ten minutes on a single result. Two short slots fit in one session, so you share the hour with someone else.

What tends to work in ten minutes:

- Pick the figure that carries the paper's main claim, or the one that surprised you most.
- Say what the paper claims it shows.
- Say whether you believe it, and why.
- Leave a few minutes for the room.

When you claim, choose "Short slot on one figure". If one short slot is already taken, the front page offers "Claim the second short slot".

## Writing a discussion synthesis

After the session you can write up what the discussion settled, and what it did not. On your page it appears as "Discussion synthesis, prepared by" your name.

It is your account of the discussion, signed by you. It is not a group position. So disagreement and unresolved questions belong in it.

One norm, which nobody checks:

- Judge the claim, not the people.
- Give your reasons.
- Say what evidence would change your mind.

To add it, press "Add to this page" at the bottom of your session page and choose "Discussion synthesis". An organiser approves it before it appears, which confirms it came from you. If you send a newer version, it replaces the old one.

The same button adds the other parts of a page:

- **What it means for our work.** How the paper connects to what people in the lab are building. It appears once an organiser approves it.
- **Slides link.** It appears once an organiser approves it.
- **Explainer link.** See the next section.
- **What happened next.** Anyone can add one at any time, and it appears within a few hours.

Everything on the site is public, under the name you give.

## Building a polished page

A plain page is a finished page. An interactive explainer is an extra, for when you want the core result to be explorable and the page worth sharing.

### Start from the template

The club keeps a starter file, `web/explainer-template.html`, in the site's repository. To get a copy, open [the starter file](explainer-template.html) and save the page from your browser. It has one figure, one slider, and marked places for the model and for the paper's result, all in the site's style.

A good explainer takes an afternoon. An LLM can write most of the code if you describe the model to it: what goes in, the equations, the parameter values from the paper, and the figure you want to reproduce. Ask it to keep everything in the one file, with nothing loaded from other sites and no browser storage. Then check its numbers against the paper yourself.

If you would like help with a first one, Max is glad to build it with you.

### The fidelity check

Before you share it, ask one question: does the visual faithfully show what the paper found? A beautiful but wrong explainer is worse than slides.

- Set the controls to the paper's values, and check that you get the paper's figure.
- Say which parts come from the paper and which are your own illustration.
- If a slider goes beyond what the paper tested, say so on the page.

### What the file needs

The site runs your file inside a sandboxed frame. That keeps visitors safe, and it sets a few limits.

- It is one self-contained HTML file, with its styles, scripts and data inside it.
- It is ideally under 2 MB. The sync does not copy a file over 10 MB.
- Any library it uses is inlined, not loaded from another site. Then the page keeps working if that site changes or disappears.
- It uses no browser storage. The frame has no origin, so `localStorage`, `sessionStorage`, IndexedDB and cookies all fail there, usually with an error that stops the script.
- It does without pop-ups, new tabs, alert boxes and forms, which the frame blocks.
- It begins like a web page, with `<!doctype html>` at the top. The template already does.

The frame is as wide as the page's text column, about 670 pixels, and between about 510 and 900 pixels tall. On a phone it is narrower. Anything taller scrolls inside the frame.

To test it, open the file in a browser with your network switched off. If it still works, nothing it needs lives on another site.

### Sharing it

Upload the file to Google Drive and set its sharing to "Anyone with the link". Any other direct https link to the file works too.

Then press "Add to this page" on your session page, choose "Explainer link", and paste the link.

Once an organiser approves it, the next sync copies the file into the club's repository, and your page shows that copy. It keeps working even if you later move or delete the original. The copy is public, and earlier versions stay in the repository's history.

If the copy fails, a message in the club's Mattermost channel names your page and says why. The usual reason is a file whose sharing is not set to "Anyone with the link".

The sync copies a file again only when its link changes. If you edit the file behind the same link, ask the co-organiser to refresh the copy.

## Sending your page to the authors

Authors often like to hear that their paper was discussed. If you want to, send them your page. The club never emails anyone for you.

A four-line email you can adapt:

> Dear [name], I presented your paper "[title]" at our lab's journal club on [date].
>
> I made a page about it, with [the discussion, or an interactive explainer]: [link to the page].
>
> If anything on it misrepresents your work, I would be glad to hear it and correct it.
>
> If you would like to reply, press "Add to this page" on the page and choose "Author reply". It appears under your name once we have checked with you that it is yours.

An author's reply shows on your page under their name. An organiser first confirms that it really came from them, and that they are happy for it to be published. That check happens only for "Author reply", which is why the email names it.
