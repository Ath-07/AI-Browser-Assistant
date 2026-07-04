import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from intent_parser import parse_intent


class TestNavigate:
    def test_go_to_url(self):
        result = parse_intent("go to google.com")
        assert result is not None
        assert result.action == "navigate"
        assert result.parameters["url"] == "https://google.com"

    def test_navigate_to_with_https(self):
        result = parse_intent("navigate to https://example.com")
        assert result is not None
        assert result.action == "navigate"
        assert result.parameters["url"] == "https://example.com"

    def test_open_url(self):
        result = parse_intent("open github.com")
        assert result is not None
        assert result.action == "navigate"
        assert result.parameters["url"] == "https://github.com"

    def test_navigate_no_match_returns_none(self):
        result = parse_intent("what is the weather")
        assert result is None


class TestFillForm:
    def test_fill_form_with_field_and_value(self):
        result = parse_intent('fill the form with John in the email field')
        assert result is not None
        assert result.action == "fill_form"
        assert result.parameters["value"] == "john"
        assert result.parameters["field_id"] == "email"

    def test_enter_text(self):
        result = parse_intent('enter "alice@test.com" in the email field')
        assert result is not None
        assert result.action == "fill_form"

    def test_fill_form_no_match(self):
        result = parse_intent("hello world")
        assert result is None or result.action != "fill_form"


class TestEmail:
    def test_send_email_to_address(self):
        result = parse_intent("send email to bob@example.com")
        assert result is not None
        assert result.action == "email"
        assert result.parameters["recipient"] == "bob@example.com"

    def test_email_to_address(self):
        result = parse_intent("email alice@work.com")
        assert result is not None
        assert result.action == "email"
        assert result.parameters["recipient"] == "alice@work.com"

    def test_email_no_match_returns_none(self):
        result = parse_intent("what is 2+2")
        assert result is None or result.action != "email"


class TestSummarize:
    def test_summarize_page(self):
        result = parse_intent("summarize this page")
        assert result is not None
        assert result.action == "summarize"
        assert result.parameters == {}

    def test_summarize_content(self):
        result = parse_intent("summarize the content")
        assert result is not None
        assert result.action == "summarize"

    def test_summarize_no_match(self):
        result = parse_intent("click the button")
        assert result is None or result.action != "summarize"


class TestClick:
    def test_click_button(self):
        result = parse_intent("click the submit button")
        assert result is not None
        assert result.action == "click"
        assert result.parameters["selector"] == "submit button"

    def test_click_on_link(self):
        result = parse_intent("click on the login link")
        assert result is not None
        assert result.action == "click"
        assert result.parameters["selector"] == "login link"

    def test_click_no_match(self):
        result = parse_intent("navigate to google.com")
        assert result is None or result.action != "click"
