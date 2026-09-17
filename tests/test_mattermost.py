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
