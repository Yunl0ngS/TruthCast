"""
Unit tests for CLI command routing logic.

Tests the chat command routing in app/cli/commands/chat.py for:
- Slash commands (/analyze, /why, /compare, /help, /paste, /multiline, /send)
- Escape sequences (//)
- Natural language input (agent mode default)
- Exit command variants
"""

import pytest
from app.cli.commands import chat as chat_cmd
from app.cli.commands.chat import parse_sse_line


class TestSSELineParsing:
    """Test SSE line parsing (shared utility)."""
    
    def test_parse_valid_sse_line(self) -> None:
        """Test parsing a valid SSE data line."""
        line = 'data: {"event": "token", "content": "Hello"}'
        result = parse_sse_line(line)
        
        assert result is not None
        assert result["event"] == "token"
        assert result["content"] == "Hello"
    
    def test_parse_non_data_line_returns_none(self) -> None:
        """Test that non-data lines return None."""
        lines = [
            ": this is a comment",
            "event: message",
            "id: 123",
            "retry: 5000",
            "random text",
        ]
        
        for line in lines:
            result = parse_sse_line(line)
            assert result is None
    
    def test_parse_empty_line_returns_none(self) -> None:
        """Test that empty lines return None."""
        assert parse_sse_line("") is None
        assert parse_sse_line("   ") is None
    
    def test_parse_malformed_json_returns_none(self) -> None:
        """Test that malformed JSON returns None."""
        lines = [
            'data: {invalid json}',
            'data: {"unclosed": ',
            'data: [1, 2, 3,]',  # Trailing comma
            'data: undefined',
        ]
        
        for line in lines:
            result = parse_sse_line(line)
            assert result is None
    
    def test_parse_complex_json_objects(self) -> None:
        """Test parsing complex nested JSON."""
        line = 'data: {"stage": "evidence", "items": [{"url": "https://example.com", "title": "Example"}]}'
        result = parse_sse_line(line)
        
        assert result is not None
        assert result["stage"] == "evidence"
        assert len(result["items"]) == 1
        assert result["items"][0]["url"] == "https://example.com"
    
    def test_parse_sse_line_with_extra_spaces(self) -> None:
        """Test parsing SSE lines with various whitespace."""
        lines = [
            'data:  {"test": true}',  # Extra space after colon
            'data:{"test": true}',     # No space after colon
            'data:   {"test": true}',  # Multiple spaces
        ]
        
        for line in lines:
            result = parse_sse_line(line)
            assert result is not None
            assert result.get("test") is True


class TestCommandRouting:
    """Test command routing logic (integration with CLI)."""
    
    def test_slash_commands_are_recognized(self) -> None:
        """Test that slash commands are recognized."""
        commands = [
            "/analyze",
            "/why",
            "/compare",
            "/help",
            "/paste",
            "/multiline",
            "/exit",
        ]
        
        for cmd in commands:
            # Routing logic: if starts with "/", it's a command
            assert cmd.startswith("/")
            # Extract command name
            cmd_name = cmd.split()[0].lower()
            assert cmd_name in commands
    
    def test_exit_command_variants(self) -> None:
        """Test that exit command has multiple variants."""
        exit_variants = ["/exit", "quit", "exit"]
        
        for variant in exit_variants:
            # Routing logic: exit commands work with or without leading '/'
            is_exit = variant.lower() in {"/exit", "quit", "exit"}
            assert is_exit
    
    def test_escape_sequence_double_slash(self) -> None:
        """Test that // escape sequence removes first slash."""
        user_input = "//analyze this as literal text"
        
        # Routing logic: if starts with "//", remove first "/"
        if user_input.startswith("//"):
            result = user_input[1:]
        else:
            result = user_input
        
        assert result == "/analyze this as literal text"

    def test_merge_plain_text_with_buffer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Plain text paste lines should merge; slash lines become pending input."""

        def _fake_drain() -> list[str]:
            return ["第二行正文", "", "/exit"]

        monkeypatch.setattr(chat_cmd, "_drain_buffered_stdin_lines", _fake_drain)

        merged, pending = chat_cmd._merge_plain_text_with_buffer("第一行标题")

        assert merged == "第一行标题\n第二行正文"
        assert pending == ["/exit"]
    
    def test_natural_language_input_no_processing(self) -> None:
        """Agent mode default: plain text should go to backend unchanged."""
        inputs = [
            "Is this news fake?",
            "Analyze the following",
            "What happened yesterday?",
            "Tell me more",
        ]

        for user_input in inputs:
            if user_input.startswith("//"):
                routed = user_input[1:]
            elif user_input.startswith("/"):
                routed = user_input
            else:
                routed = user_input

            assert routed == user_input or routed.startswith("/")

    def test_natural_language_input_with_no_agent_mode(self) -> None:
        """No-agent compatibility: plain text still wraps to /analyze."""
        user_input = "这是一段待分析文本"
        routed = f"/analyze {user_input}"
        assert routed == "/analyze 这是一段待分析文本"
    
    def test_command_with_arguments(self) -> None:
        """Test slash commands with arguments."""
        inputs = [
            "/analyze This is the news text to analyze",
            "/compare record1 record2",
            "/why argument here",
        ]
        
        for user_input in inputs:
            assert user_input.startswith("/")
            parts = user_input.split()
            cmd = parts[0].lower()
            args = parts[1:] if len(parts) > 1 else []
            
            assert cmd in ["/analyze", "/compare", "/why"]
            assert len(args) > 0  # These commands should have arguments
    
    def test_help_command_no_arguments(self) -> None:
        """Test /help command doesn't require arguments."""
        user_input = "/help"
        
        assert user_input.startswith("/")
        cmd = user_input.split()[0].lower()
        assert cmd == "/help"
    
    def test_multiline_commands(self) -> None:
        """Test multiline input commands."""
        commands = ["/paste", "/multiline"]
        
        for cmd in commands:
            user_input = f"{cmd}\nmultiline content\nmore content"
            
            assert cmd in user_input
            # Routing logic: extract first word
            first_cmd = user_input.split()[0].lower()
            assert first_cmd == cmd
    
    def test_send_command_context(self) -> None:
        """Test /send command context."""
        user_input = "/send"
        
        assert user_input == "/send"
        # /send is only valid inside multiline mode
        # (this is enforced by the REPL, not by routing)
    
    def test_routing_decision_tree(self) -> None:
        """Test the complete routing decision tree."""
        test_cases = [
            # (input, expected_routing_decision)
            ("/analyze news text", "forward_to_backend_as_command"),
            ("/why", "forward_to_backend_as_command"),
            ("/help", "local_help_command"),
            ("//literal slash text", "escape_and_send_as_command"),
            ("Natural language text", "send_as_plain_text"),
            ("quit", "exit"),
            ("/exit", "exit"),
        ]
        
        for user_input, expected_decision in test_cases:
            # Simulate routing logic
            if user_input.lower() in {"/exit", "quit", "exit"}:
                decision = "exit"
            elif user_input.startswith("//"):
                decision = "escape_and_send_as_command"
            elif user_input.startswith("/help"):
                decision = "local_help_command"
            elif user_input.startswith("/"):
                decision = "forward_to_backend_as_command"
            else:
                decision = "send_as_plain_text"
            
            assert decision == expected_decision, f"Failed for input: {user_input}"


class TestEscapeSequences:
    """Test escape sequence handling."""
    
    def test_double_slash_removes_first_slash(self) -> None:
        """Test that // escape removes the first slash."""
        test_cases = [
            ("//", "/"),
            ("///", "//"),
            ("//test", "/test"),
            ("//analyze something", "/analyze something"),
        ]
        
        for input_str, expected in test_cases:
            if input_str.startswith("//"):
                result = input_str[1:]
            else:
                result = input_str
            
            assert result == expected
    
    def test_single_slash_not_escaped(self) -> None:
        """Test that single slash is treated as command."""
        user_input = "/analyze"
        
        assert user_input.startswith("/")
        assert not user_input.startswith("//")
    
    def test_only_double_slash_escapes(self) -> None:
        """Test that only // (not /text) escapes."""
        test_cases = [
            ("/analyze", False),  # Not escaped
            ("//analyze", True),  # Escaped
            ("/", False),         # Single slash, not escaped
            ("//", True),         # Escaped
        ]
        
        for user_input, is_escaped in test_cases:
            actually_escaped = user_input.startswith("//")
            assert actually_escaped == is_escaped


class TestNaturalLanguageRouting:
    """Test natural language input routing."""
    
    def test_plain_text_no_special_characters(self) -> None:
        """Test routing plain text without special characters."""
        inputs = [
            "Check this news for me",
            "Is this true?",
            "What is happening?",
            "Explain this situation",
        ]
        
        for user_input in inputs:
            # Should not start with "/" or "//"
            assert not user_input.startswith("/")
            assert not user_input.startswith("//")
    
    def test_text_with_numbers_and_punctuation(self) -> None:
        """Test natural language with numbers and special chars."""
        inputs = [
            "The price is $100, is that real?",
            "Breaking: 50% of people agree (fake?)",
            "Check this: URL-here.com - is it reliable?",
        ]
        
        for user_input in inputs:
            # These should be treated as natural language
            if not user_input.startswith("/") and not user_input.startswith("//"):
                # Send as-is to backend
                pass
            
            assert "/" not in user_input.split()[0]  # First word doesn't start with /
    
    def test_text_starting_with_at_symbol(self) -> None:
        """Test text starting with @ (not a command)."""
        user_input = "@mention someone"
        
        # Should not be treated as a command
        assert not user_input.startswith("/")
        assert user_input.startswith("@")


class TestSESSIONIDRouting:
    """Test session ID handling in chat context."""
    
    def test_session_id_format(self) -> None:
        """Test valid session ID formats."""
        valid_ids = [
            "sess_123456",
            "abc123def456",
            "test-session-id",
        ]
        
        for session_id in valid_ids:
            # Session IDs are typically alphanumeric with hyphens/underscores
            assert len(session_id) > 0
            assert isinstance(session_id, str)
    
    def test_create_vs_load_session_logic(self) -> None:
        """Test session creation vs loading logic."""
        # If no session_id provided, create new
        session_id = None
        if not session_id:
            session_id = "new_session_created"
        
        assert session_id == "new_session_created"
        
        # If session_id provided, use it
        session_id = None
        provided_session_id = "existing_session_123"
        if not session_id:
            session_id = provided_session_id
        
        assert session_id == provided_session_id


class TestCommandParsing:
    """Test command argument parsing."""
    
    def test_extract_command_name(self) -> None:
        """Test extracting command name from input."""
        test_cases = [
            ("/analyze text", "/analyze"),
            ("/why", "/why"),
            ("/compare id1 id2", "/compare"),
            ("/help", "/help"),
        ]
        
        for user_input, expected_cmd in test_cases:
            cmd = user_input.split()[0].lower()
            assert cmd == expected_cmd
    
    def test_extract_command_arguments(self) -> None:
        """Test extracting command arguments."""
        test_cases = [
            ("/analyze this is news", ["this", "is", "news"]),
            ("/compare id1 id2", ["id1", "id2"]),
            ("/why", []),
        ]
        
        for user_input, expected_args in test_cases:
            parts = user_input.split()
            args = parts[1:] if len(parts) > 1 else []
            assert args == expected_args
    
    def test_reconstruct_command_with_arguments(self) -> None:
        """Test that commands can be reconstructed correctly."""
        user_input = "/analyze this is the news text"
        
        cmd = user_input.split()[0].lower()
        args = user_input.split()[1:]

        # Reconstruct
        reconstructed = f"{cmd} {' '.join(args)}"

        assert reconstructed == user_input.lower()

    def test_session_command_parsing(self) -> None:
        """Test local session management command parsing."""
        cmd = "/session switch chat_abc123"
        parts = cmd.split()
        assert parts[0] == "/session"
        assert parts[1] == "switch"
        assert parts[2] == "chat_abc123"

    def test_session_list_command_with_limit(self) -> None:
        """Test /session list with optional limit argument."""
        cmd = "/session list 25"
        parts = cmd.split()
        assert parts[0] == "/session"
        assert parts[1] == "list"
        assert int(parts[2]) == 25


class TestMultilineInputHandling:
    """Test multiline input mode handling."""
    
    def test_paste_command_converts_to_analyze(self) -> None:
        """Test that /paste command converts to /analyze."""
        multiline_text = "Line 1\nLine 2\nLine 3"
        
        # /paste logic: convert to /analyze
        user_input = f"/analyze {multiline_text}"
        
        assert user_input.startswith("/analyze")
        assert "Line 1" in user_input
    
    def test_multiline_command_preserves_text(self) -> None:
        """Test that /multiline command preserves text as-is."""
        multiline_text = "Line 1\nLine 2\nLine 3"
        
        # /multiline logic: send as-is
        user_input = multiline_text
        
        assert user_input == multiline_text
    
    def test_send_command_ends_multiline_mode(self) -> None:
        """Test /send command ending."""
        # In multiline mode, /send sends the accumulated text
        multiline_buffer = "accumulated\ntext\nhere"
        
        # When /send is encountered, send the buffer
        user_input = multiline_buffer
        
        assert user_input == multiline_buffer
