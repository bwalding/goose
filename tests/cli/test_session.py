from unittest.mock import MagicMock, patch

import pytest
from exchange import Exchange, Message, ToolUse, ToolResult
from goose.cli.prompt.goose_prompt_session import GoosePromptSession
from goose.cli.prompt.user_input import PromptAction, UserInput
from goose.cli.session import Session
from prompt_toolkit import PromptSession

SPECIFIED_SESSION_NAME = "mySession"
SESSION_NAME = "test"


@pytest.fixture
def mock_specified_session_name():
    with patch.object(PromptSession, "prompt", return_value=SPECIFIED_SESSION_NAME) as specified_session_name:
        yield specified_session_name


@pytest.fixture
def create_session_with_mock_configs(mock_sessions_path, exchange_factory, profile_factory):
    with patch("goose.cli.session.build_exchange") as mock_exchange, patch(
        "goose.cli.session.load_profile", return_value=profile_factory()
    ), patch("goose.cli.session.SessionNotifier") as mock_session_notifier, patch(
        "goose.cli.session.load_provider", return_value="provider"
    ):
        mock_session_notifier.return_value = MagicMock()
        mock_exchange.return_value = exchange_factory()

        def create_session(session_attributes: dict = {}):
            return Session(**session_attributes)

        yield create_session


def test_session_does_not_extend_last_user_text_message_on_init(
    create_session_with_mock_configs, mock_sessions_path, create_session_file
):
    messages = [Message.user("Hello"), Message.assistant("Hi"), Message.user("Last should be removed")]
    create_session_file(messages, mock_sessions_path / f"{SESSION_NAME}.jsonl")

    session = create_session_with_mock_configs({"name": SESSION_NAME})
    print("Messages after session init:", session.exchange.messages)  # Debugging line
    assert len(session.exchange.messages) == 2
    assert [message.text for message in session.exchange.messages] == ["Hello", "Hi"]


def test_session_adds_resume_message_if_last_message_is_tool_result(
    create_session_with_mock_configs, mock_sessions_path, create_session_file
):
    messages = [
        Message.user("Hello"),
        Message(role="assistant", content=[ToolUse(id="1", name="first_tool", parameters={})]),
        Message(role="user", content=[ToolResult(tool_use_id="1", output="output")]),
    ]
    create_session_file(messages, mock_sessions_path / f"{SESSION_NAME}.jsonl")

    session = create_session_with_mock_configs({"name": SESSION_NAME})
    print("Messages after session init:", session.exchange.messages)  # Debugging line
    assert len(session.exchange.messages) == 4
    assert session.exchange.messages[-1].role == "assistant"
    assert session.exchange.messages[-1].text == "I see we were interrupted. How can I help you?"


def test_session_removes_tool_use_and_adds_resume_message_if_last_message_is_tool_use(
    create_session_with_mock_configs, mock_sessions_path, create_session_file
):
    messages = [
        Message.user("Hello"),
        Message(role="assistant", content=[ToolUse(id="1", name="first_tool", parameters={})]),
    ]
    create_session_file(messages, mock_sessions_path / f"{SESSION_NAME}.jsonl")

    session = create_session_with_mock_configs({"name": SESSION_NAME})
    print("Messages after session init:", session.exchange.messages)  # Debugging line
    assert len(session.exchange.messages) == 2
    assert [message.text for message in session.exchange.messages] == [
        "Hello",
        "I see we were interrupted. How can I help you?",
    ]


def test_process_first_message_return_message(create_session_with_mock_configs):
    session = create_session_with_mock_configs()
    with patch.object(
        GoosePromptSession, "get_user_input", return_value=UserInput(action=PromptAction.CONTINUE, text="Hello")
    ):
        message = session.process_first_message()

        assert message.text == "Hello"
        assert len(session.exchange.messages) == 0


def test_process_first_message_to_exit(create_session_with_mock_configs):
    session = create_session_with_mock_configs()
    with patch.object(GoosePromptSession, "get_user_input", return_value=UserInput(action=PromptAction.EXIT)):
        message = session.process_first_message()

        assert message is None


def test_process_first_message_return_last_exchange_message(create_session_with_mock_configs):
    session = create_session_with_mock_configs()
    session.exchange.messages.append(Message.user("Hi"))

    message = session.process_first_message()

    assert message.text == "Hi"
    assert len(session.exchange.messages) == 0


def test_log_log_cost(create_session_with_mock_configs):
    session = create_session_with_mock_configs()
    mock_logger = MagicMock()
    cost_message = "You have used 100 tokens"
    with patch("exchange.Exchange.get_token_usage", return_value={}), patch(
        "goose.cli.session.get_total_cost_message", return_value=cost_message
    ), patch("goose.cli.session.get_logger", return_value=mock_logger):
        session._log_cost()
        mock_logger.info.assert_called_once_with(cost_message)


def test_run_should_auto_save_session(create_session_with_mock_configs, mock_sessions_path):
    def custom_exchange_generate(self, *args, **kwargs):
        message = Message.assistant("Response")
        self.add(message)
        return message

    user_inputs = [
        UserInput(action=PromptAction.CONTINUE, text="Question1"),
        UserInput(action=PromptAction.CONTINUE, text="Question2"),
        UserInput(action=PromptAction.EXIT),
    ]

    session = create_session_with_mock_configs({"name": SESSION_NAME})
    with patch.object(GoosePromptSession, "get_user_input", side_effect=user_inputs), patch.object(
        Exchange, "generate"
    ) as mock_generate, patch("goose.cli.session.save_latest_session") as mock_save_latest_session:
        mock_generate.side_effect = lambda *args, **kwargs: custom_exchange_generate(session.exchange, *args, **kwargs)
        session.run()

        session_file = mock_sessions_path / f"{SESSION_NAME}.jsonl"
        assert session.exchange.generate.call_count == 2
        assert mock_save_latest_session.call_count == 2
        assert mock_save_latest_session.call_args_list[0][0][0] == session_file
        assert session_file.exists()


def test_set_generated_session_name(create_session_with_mock_configs, mock_sessions_path):
    generated_session_name = "generated_session_name"
    with patch("goose.cli.session.droid", return_value=generated_session_name):
        session = create_session_with_mock_configs({"name": None})
        assert session.name == generated_session_name
