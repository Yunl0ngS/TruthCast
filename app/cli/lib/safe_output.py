"""
Unified Windows GBK-safe output strategy for CLI.

Provides safe printing to stdout/stderr with graceful fallback for non-UTF-8 terminals.
Strategy: no forced UTF-8; printable if possible, otherwise replacement fallback.
"""

import sys
from typing import Optional

import typer


def supports_unicode() -> bool:
    """
    Check if console supports unicode/emoji output.
    
    Returns:
        True if the terminal encoding can handle unicode.
    """
    try:
        # Try encoding a test emoji
        "\u2705".encode(sys.stdout.encoding or "utf-8")
        return True
    except (UnicodeEncodeError, LookupError):
        return False


# Module-level cache for unicode support detection
_UNICODE_SUPPORT = supports_unicode()


def emoji(unicode_char: str, ascii_fallback: str) -> str:
    """
    Return emoji if supported, otherwise ASCII fallback.
    
    This allows graceful degradation in GBK/cp936 terminals where emoji
    cannot be rendered. The fallback uses ASCII bracketed labels like [ERROR].
    
    Args:
        unicode_char: Unicode emoji character
        ascii_fallback: ASCII fallback (e.g., '[ERROR]')
    
    Returns:
        Either the unicode_char or ascii_fallback
    """
    return unicode_char if _UNICODE_SUPPORT else ascii_fallback


def safe_print(
    text: str, 
    end: str = "\n", 
    flush: bool = False,
    err: bool = False
) -> None:
    """
    Print text with terminal-encoding fallback.
    
    Unified output method for both stdout and stderr. If the text contains
    characters not supported by the terminal encoding (e.g., GBK/cp936),
    they are replaced with the replacement character (U+FFFD).
    
    Args:
        text: Text to print
        end: String appended after the last value (default: newline)
        flush: Whether to forcibly flush the stream (default: False)
        err: Whether to print to stderr instead of stdout (default: False)
    """
    if err:
        # Delegate to stderr-specific handler
        safe_print_err(text, end=end, flush=flush)
    else:
        # stdout path
        try:
            print(text, end=end, flush=flush)
        except UnicodeEncodeError:
            # Fallback: encode to terminal's encoding with replacement character
            encoding = sys.stdout.encoding or "utf-8"
            try:
                sanitized = text.encode(encoding, errors="replace").decode(
                    encoding, errors="replace"
                )
                print(sanitized, end=end, flush=flush)
            except Exception:
                # Last resort: use ascii-only representation
                ascii_repr = text.encode("ascii", errors="replace").decode("ascii")
                print(ascii_repr, end=end, flush=flush)


def safe_print_err(text: str, end: str = "\n", flush: bool = False) -> None:
    """
    Print error text to stderr with terminal-encoding fallback.
    
    Uses typer.echo(err=True) for consistent error output. Falls back
    to encoding with replacement character if the terminal cannot render
    the output.
    
    Args:
        text: Error message to print
        end: String appended after the last value (default: newline)
        flush: Whether to forcibly flush the stream (default: False)
    """
    try:
        # typer.echo(err=True) writes to stderr
        typer.echo(text, err=True, nl=(end == "\n"))
        if flush:
            sys.stderr.flush()
    except UnicodeEncodeError:
        # Fallback: encode to terminal's encoding with replacement character
        encoding = sys.stderr.encoding or "utf-8"
        try:
            sanitized = text.encode(encoding, errors="replace").decode(
                encoding, errors="replace"
            )
            typer.echo(sanitized, err=True, nl=(end == "\n"))
            if flush:
                sys.stderr.flush()
        except Exception:
            # Last resort: use ascii-only representation
            ascii_repr = text.encode("ascii", errors="replace").decode("ascii")
            typer.echo(ascii_repr, err=True, nl=(end == "\n"))
            if flush:
                sys.stderr.flush()


def decode_bytes(
    data: bytes, preferred_encodings: Optional[list[str]] = None
) -> str:
    """
    Decode bytes with best-effort fallback for various encodings.
    
    Tries a list of encodings in order:
    1. User-provided preferred encodings (if any)
    2. System stdin encoding
    3. UTF-8 (universal fallback)
    4. GB18030 (superset of GBK, supports all Chinese characters)
    5. ASCII with replacement (last resort)
    
    Args:
        data: Byte string to decode
        preferred_encodings: Optional list of encodings to try first
    
    Returns:
        Decoded string (with replacement character for undecodable bytes)
    """
    candidates = preferred_encodings or []
    candidates.extend(
        k for k in [
            "utf-8",
            getattr(sys.stdin, "encoding", None),
            "gb18030",
        ] if k
    )
    
    for encoding in candidates:
        if not encoding:
            continue
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    
    # Last resort: decode with replacement
    return data.decode("utf-8", errors="replace")
