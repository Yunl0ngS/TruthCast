"""
Unit tests for CLI SSE parsing functionality.

Tests the parse_sse_line() function which parses Server-Sent Events from the backend.
Covers all event types (token, stage, message, done, error) and edge cases.
"""

import json
from typing import Dict, Any, Optional

import pytest

from app.cli.commands.chat import parse_sse_line


class TestSSELineParsing:
    """Test SSE line parsing with all event types."""
    
    def test_parse_token_event(self) -> None:
        """Test parsing a token event (streaming text chunk)."""
        line = 'data: {"type": "token", "data": {"content": "hello"}}'
        result = parse_sse_line(line)
        
        assert result is not None
        assert result["type"] == "token"
        assert result["data"]["content"] == "hello"
    
    def test_parse_stage_event(self) -> None:
        """Test parsing a stage event (progress update)."""
        line = 'data: {"type": "stage", "data": {"stage": "claims", "status": "running"}}'
        result = parse_sse_line(line)
        
        assert result is not None
        assert result["type"] == "stage"
        assert result["data"]["stage"] == "claims"
        assert result["data"]["status"] == "running"
    
    def test_parse_message_event(self) -> None:
        """Test parsing a message event (structured response)."""
        message_data = {
            "content": "analysis result",
            "actions": [{"label": "details", "command": "/why"}],
            "references": [{"title": "source1", "href": "http://example.com"}]
        }
        line = f'data: {{"type": "message", "data": {{"message": {json.dumps(message_data)}}}}}'
        result = parse_sse_line(line)
        
        assert result is not None
        assert result["type"] == "message"
        assert result["data"]["message"]["content"] == "analysis result"
    
    def test_parse_done_event(self) -> None:
        """Test parsing a done event (stream completion)."""
        line = 'data: {"type": "done"}'
        result = parse_sse_line(line)
        
        assert result is not None
        assert result["type"] == "done"
    
    def test_parse_error_event(self) -> None:
        """Test parsing an error event."""
        line = 'data: {"type": "error", "data": {"message": "server error"}}'
        result = parse_sse_line(line)
        
        assert result is not None
        assert result["type"] == "error"
        assert result["data"]["message"] == "server error"
    
    def test_empty_line(self) -> None:
        """Test that empty lines return None."""
        assert parse_sse_line("") is None
        assert parse_sse_line("   ") is None
        assert parse_sse_line("\t\t") is None
    
    def test_non_data_line(self) -> None:
        """Test that non-data lines return None."""
        assert parse_sse_line("event: token") is None
        assert parse_sse_line(": comment") is None
        assert parse_sse_line("id: 123") is None
        assert parse_sse_line("retry: 5000") is None
    
    def test_malformed_json(self) -> None:
        """Test parsing with malformed JSON returns None."""
        assert parse_sse_line('data: {invalid json}') is None
        assert parse_sse_line('data: {"incomplete": ') is None
        assert parse_sse_line('data: [1, 2, ') is None
    
    def test_data_prefix_variations(self) -> None:
        """Test various data prefix formats."""
        result = parse_sse_line('data: {"type": "token"}')
        assert result is not None
        
        result = parse_sse_line('data:  {"type": "token"}')
        assert result is not None
        
        result = parse_sse_line('data:{"type": "token"}')
        assert result is not None
    
    def test_numeric_content(self) -> None:
        """Test numeric values in SSE data."""
        line = 'data: {"type": "token", "data": {"confidence": 0.95, "count": 42}}'
        result = parse_sse_line(line)
        
        assert result is not None
        assert result["data"]["confidence"] == 0.95
        assert result["data"]["count"] == 42
    
    def test_boolean_values(self) -> None:
        """Test boolean values in SSE data."""
        line = 'data: {"type": "token", "data": {"is_final": true, "is_error": false}}'
        result = parse_sse_line(line)
        
        assert result is not None
        assert result["data"]["is_final"] is True
        assert result["data"]["is_error"] is False
    
    def test_array_in_data(self) -> None:
        """Test array values in SSE data."""
        line = 'data: {"type": "message", "data": {"items": [1, 2, 3, "four"]}}'
        result = parse_sse_line(line)
        
        assert result is not None
        assert result["data"]["items"] == [1, 2, 3, "four"]
    
    def test_nested_json_structures(self) -> None:
        """Test parsing deeply nested JSON structures."""
        nested = {
            "type": "message",
            "data": {
                "message": {
                    "content": "test",
                    "metadata": {"nested": {"deep": {"value": "found"}}}
                }
            }
        }
        line = f'data: {json.dumps(nested)}'
        result = parse_sse_line(line)
        
        assert result is not None
        assert result["data"]["message"]["metadata"]["nested"]["deep"]["value"] == "found"
    
    def test_case_sensitivity_of_data_prefix(self) -> None:
        """Test that 'data:' is case-sensitive."""
        assert parse_sse_line('Data: {"type": "token"}') is None
        assert parse_sse_line('DATA: {"type": "token"}') is None
    
    def test_very_long_json(self) -> None:
        """Test parsing very long JSON payloads."""
        long_content = "x" * 10000
        line = f'data: {{"type": "token", "data": {{"content": "{long_content}"}}}}'
        result = parse_sse_line(line)
        
        assert result is not None
        assert len(result["data"]["content"]) == 10000
    
    def test_json_with_extra_whitespace(self) -> None:
        """Test JSON with various whitespace."""
        line = 'data: { "type" : "token" , "data" : { "content" : "test" } }'
        result = parse_sse_line(line)
        
        assert result is not None
        assert result["type"] == "token"


class TestSSEMultilineScenarios:
    """Test SSE parsing in realistic streaming scenarios."""
    
    def test_multiple_tokens_sequence(self) -> None:
        """Test parsing sequence of token events."""
        events = [
            'data: {"type": "token", "data": {"content": "hello"}}',
            'data: {"type": "token", "data": {"content": " "}}',
            'data: {"type": "token", "data": {"content": "world"}}',
            'data: {"type": "done"}',
        ]
        
        results = [parse_sse_line(line) for line in events]
        
        assert len(results) == 4
        assert all(r is not None for r in results)
        assert results[0]["data"]["content"] == "hello"
        assert results[1]["data"]["content"] == " "
        assert results[2]["data"]["content"] == "world"
        assert results[3]["type"] == "done"
    
    def test_token_stage_message_sequence(self) -> None:
        """Test typical sequence: tokens, stage update, message, done."""
        lines = [
            'data: {"type": "token", "data": {"content": "analyzing"}}',
            'data: {"type": "stage", "data": {"stage": "report", "status": "done"}}',
            'data: {"type": "message", "data": {"message": {"content": "complete"}}}',
            'data: {"type": "done"}',
        ]
        
        for line in lines:
            result = parse_sse_line(line)
            assert result is not None
    
    def test_skip_comment_lines(self) -> None:
        """Test that SSE comment lines are skipped."""
        lines = [
            ': this is a comment',
            'data: {"type": "token", "data": {"content": "hello"}}',
            ': another comment',
            'data: {"type": "done"}',
        ]
        
        results = [parse_sse_line(line) for line in lines]
        
        assert results[0] is None
        assert results[1] is not None
        assert results[2] is None
        assert results[3] is not None


class TestSSEErrorRecovery:
    """Test error handling and recovery in SSE parsing."""
    
    def test_skip_malformed_continue_parsing(self) -> None:
        """Test that malformed events can be skipped and parsing continues."""
        lines = [
            'data: {"type": "token", "data": {"content": "start"}}',
            'data: {invalid}',
            'data: {"type": "token", "data": {"content": "continue"}}',
            'data: {"type": "done"}',
        ]
        
        results = [parse_sse_line(line) for line in lines]
        
        assert results[0] is not None
        assert results[1] is None
        assert results[2] is not None
        assert results[3] is not None
    
    def test_empty_lines_between_events(self) -> None:
        """Test handling of empty lines between SSE events."""
        lines = [
            'data: {"type": "token", "data": {"content": "hello"}}',
            '',
            'data: {"type": "token", "data": {"content": "world"}}',
            '',
            'data: {"type": "done"}',
        ]
        
        results = [parse_sse_line(line) for line in lines]
        
        assert results[0] is not None
        assert results[1] is None
        assert results[2] is not None
        assert results[3] is None
        assert results[4] is not None
