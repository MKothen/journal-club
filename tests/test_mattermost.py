from sync.mattermost import post


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

from sync.mattermost import neutral  # noqa: E402

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
