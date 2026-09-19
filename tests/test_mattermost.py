import re

from sync.mattermost import neutral, post


def test_the_message_is_posted_as_json_text():
    sent = {}

    def poster(url, json, timeout):
        sent["url"] = url
        sent["json"] = json

        class Response:
            status_code = 200

            def raise_for_status(self):
                return None

        return Response()

    assert post("hello", "https://mm.example/hooks/abc", poster) is True
    assert sent["json"] == {"text": "hello"}


def test_without_a_webhook_it_reports_failure_instead_of_raising(capsys):
    assert post("hello", None) is False
    assert "hello" in capsys.readouterr().out


# -- final review I4: public form text is inert in a post ------------------------------

ZWSP = chr(0x200B)
BACKSLASH = chr(92)


def test_neutral_breaks_every_mention():
    assert neutral("@channel and @all") == f"@{ZWSP}channel and @{ZWSP}all"


def test_neutral_collapses_whitespace_and_newlines_to_single_spaces():
    assert neutral("  Ann\n\n de\tVries\r\n") == "Ann de Vries"


def test_neutral_backslash_escapes_markdown_and_the_backslash_first():
    special = BACKSLASH + "`*_~[]()#>|!<"
    assert neutral(special) == "".join(BACKSLASH + c for c in special)


def test_neutral_leaves_plain_text_alone():
    assert neutral("Bo de Vries, 10.1038/nn.2479") == "Bo de Vries, 10.1038/nn.2479"


# -- final re-review: an HTML entity must not smuggle a mention past neutral ------------
# Mattermost decodes entities such as &commat; into "@" before it looks for mentions,
# so "&commat;channel" typed into the form would notify the whole channel.

ENTITY = re.compile(r"&[A-Za-z0-9#]+;")


def test_neutral_leaves_no_html_entity_that_could_decode_into_a_mention():
    for typed in ("&commat;channel", "&commat;here", "&commat;all",
                  "&#64;channel", "&#x40;here", "&amp;commat;all"):
        assert not ENTITY.search(neutral(typed)), typed


def test_neutral_escapes_an_ampersand_and_breaks_it_from_what_follows():
    assert neutral("&commat;channel") == BACKSLASH + "&" + ZWSP + "commat;channel"


# -- final review D5: with no webhook, each message goes to the run summary ------------

FENCE = chr(96) * 3


def test_without_a_webhook_the_message_is_appended_to_the_run_summary(tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    summary.write_text("earlier" + chr(10), encoding="utf-8")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert post("Ann claimed *Wednesday*", None) is False
    assert post("second", None) is False
    nl = chr(10)
    assert summary.read_text(encoding="utf-8") == (
        "earlier" + nl
        + FENCE + "text" + nl + "Ann claimed *Wednesday*" + nl + FENCE + nl + nl
        + FENCE + "text" + nl + "second" + nl + FENCE + nl + nl)


def test_a_run_of_backticks_cannot_close_the_summary_fence(tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    post("a " + FENCE + " b " + chr(96) * 5, None)
    body = summary.read_text(encoding="utf-8").split(chr(10))[1]
    assert FENCE not in body
    assert body.startswith("a ")


def test_without_a_webhook_or_a_summary_it_only_prints(tmp_path, capsys):
    assert post("hello", None) is False
    assert "hello" in capsys.readouterr().out
