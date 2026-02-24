"""Tests for CLI safe output handling with encoding fallback."""

import io
import sys
from unittest import mock

import pytest

from app.cli.lib.safe_output import (
    decode_bytes,
    emoji,
    safe_print,
    safe_print_err,
    supports_unicode,
)


class TestUnicodeSupport:
    """Test unicode/emoji support detection."""

    def test_emoji_provides_fallback(self):
        """Test emoji always returns either unicode or ascii fallback."""
        unicode_char = "❌"
        ascii_fallback = "[ERROR]"
        result = emoji(unicode_char, ascii_fallback)
        assert result in [unicode_char, ascii_fallback]


class TestDecodeBytes:
    """Test decode_bytes function with various encodings."""

    def test_decode_utf8_bytes(self):
        """Test decoding UTF-8 encoded bytes."""
        text = "Hello, World!"
        data = text.encode('utf-8')
        result = decode_bytes(data)
        assert result == text

    def test_decode_chinese_utf8(self):
        """Test decoding Chinese characters in UTF-8."""
        text = "你好世界"
        data = text.encode('utf-8')
        result = decode_bytes(data)
        assert result == text

    def test_decode_gb18030(self):
        """Test decoding GB18030 (Chinese encoding)."""
        text = "你好世界"
        data = text.encode('gb18030')
        result = decode_bytes(data, preferred_encodings=['gb18030'])
        assert result == text

    def test_decode_with_preferred_encodings(self):
        """Test decode_bytes respects preferred encodings list."""
        text = "你好"
        data = text.encode('gbk')
        result = decode_bytes(data, preferred_encodings=['gbk'])
        assert result == text

    def test_decode_invalid_bytes_fallback(self):
        """Test decode_bytes handles invalid bytes with replacement."""
        data = b'\x80\x81\x82\x83'
        result = decode_bytes(data)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_decode_empty_bytes(self):
        """Test decode_bytes with empty input."""
        result = decode_bytes(b'')
        assert result == ""

    def test_decode_ascii_subset(self):
        """Test decode_bytes with ASCII subset."""
        text = "ABC123!@#"
        for encoding in ['utf-8', 'gbk', 'gb18030', 'ascii']:
            data = text.encode(encoding)
            result = decode_bytes(data)
            assert result == text


class TestEncodingRoundtrip:
    """Test encoding/decoding roundtrips."""

    def test_chinese_text_roundtrip(self):
        """Test encoding/decoding Chinese text."""
        original = "重大虚假信息需要核查"
        for encoding in ['utf-8', 'gb18030', 'gbk']:
            try:
                encoded = original.encode(encoding)
                decoded = decode_bytes(encoded, preferred_encodings=[encoding])
                assert decoded == original, f"Roundtrip failed for {encoding}"
            except LookupError:
                pass

    def test_mixed_ascii_unicode_text(self):
        """Test text with ASCII and unicode."""
        text = "Error: 文件不存在 (File not found)"
        encoded = text.encode('utf-8')
        decoded = decode_bytes(encoded)
        assert decoded == text


class TestGBKSpecificHandling:
    """Test handling for Windows GBK/cp936 terminals."""

    def test_decode_candidates_include_gb18030(self):
        """Test GB18030 is in fallback chain."""
        text = "测试中文"
        data = text.encode('gb18030')
        result = decode_bytes(data)
        assert result == text

    def test_control_chars_dont_crash(self):
        """Test that control characters don't crash output."""
        text = "Normal\x00\x01\x02text"
        with mock.patch('builtins.print'):
            safe_print(text)


class TestIntegration:
    """Integration tests for safe output pipeline."""

    def test_emoji_safe_print_combination(self):
        """Test emoji and safe_print work together."""
        with mock.patch('builtins.print'):
            error_emoji = emoji("❌", "[ERROR]")
            message = f"{error_emoji} Something went wrong"
            safe_print(message)

    def test_decode_then_safe_print(self):
        """Test pattern: decode bytes then safely print."""
        raw_text = "用户输入: test data"
        data = raw_text.encode('utf-8')
        text = decode_bytes(data)
        with mock.patch('builtins.print'):
            safe_print(text)

    def test_error_message_with_emoji_and_encoding(self):
        """Test error message with emoji and Unicode."""
        with mock.patch('typer.echo'):
            error_emoji = emoji("❌", "[ERROR]")
            message = f"{error_emoji} 文件不存在: config.json"
            safe_print_err(message)
