"""
Unit tests for CLI HTTP client error handling and retry logic.

Tests the APIClient class in app/cli/client.py for network errors, timeouts,
HTTP status codes, and retry mechanisms.
"""

import json
from unittest.mock import Mock, patch

import pytest
import httpx

from app.cli.client import (
    APIClient,
    APIError,
    NetworkError,
    TimeoutError as ClientTimeoutError,
    HTTPStatusError,
    JSONParseError,
)


class TestHTTPClientInitialization:
    """Test APIClient initialization and configuration."""
    
    def test_client_initialization_defaults(self) -> None:
        """Test client initializes with default values."""
        client = APIClient()
        
        assert client.base_url == "http://127.0.0.1:8000"
        assert client.timeout == 30.0
        assert client.retry_times == 1
        
        client.close()
    
    def test_client_initialization_custom_values(self) -> None:
        """Test client initializes with custom values."""
        client = APIClient(
            base_url="http://example.com:9000",
            timeout=60.0,
            retry_times=3,
        )
        
        assert client.base_url == "http://example.com:9000"
        assert client.timeout == 60.0
        assert client.retry_times == 3
        
        client.close()
    
    def test_client_context_manager(self) -> None:
        """Test client works as context manager."""
        with APIClient() as client:
            assert client is not None
            assert client.base_url == "http://127.0.0.1:8000"


class TestHTTPClientNetworkErrors:
    """Test network error handling."""
    
    def test_connection_refused_error(self) -> None:
        """Test handling of connection refused errors."""
        client = APIClient(base_url="http://127.0.0.1:9999", retry_times=1)
        
        with patch.object(client._client, 'get') as mock_get:
            mock_get.side_effect = httpx.ConnectError("Connection refused")
            
            with pytest.raises(NetworkError):
                client.get("/test")
        
        client.close()
    
    def test_dns_failure_error(self) -> None:
        """Test handling of DNS resolution failures."""
        client = APIClient(base_url="http://invalid-host-12345.local", retry_times=1)
        
        with patch.object(client._client, 'get') as mock_get:
            mock_get.side_effect = httpx.NetworkError("Name resolution failed")
            
            with pytest.raises(NetworkError):
                client.get("/test")
        
        client.close()
    
    def test_retry_on_network_error(self) -> None:
        """Test that client retries on network errors."""
        client = APIClient(retry_times=3)
        
        with patch.object(client._client, 'get') as mock_get:
            mock_get.side_effect = httpx.ConnectError("Connection refused")
            
            with pytest.raises(NetworkError):
                client.get("/test")
            
            assert mock_get.call_count == 3
        
        client.close()
    
    def test_retry_success_on_third_attempt(self) -> None:
        """Test successful request after retries."""
        client = APIClient(retry_times=3)
        
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "ok"}
        
        with patch.object(client._client, 'get') as mock_get:
            mock_get.side_effect = [
                httpx.ConnectError("Connection refused"),
                httpx.ConnectError("Connection refused"),
                mock_response,
            ]
            
            result = client.get("/test")
            
            assert result == {"status": "ok"}
            assert mock_get.call_count == 3
        
        client.close()


class TestHTTPClientTimeoutErrors:
    """Test timeout error handling."""
    
    def test_connect_timeout(self) -> None:
        """Test handling of connection timeout errors (ConnectTimeout → NetworkError)."""
        client = APIClient(timeout=5.0, retry_times=1)
        
        with patch.object(client._client, 'get') as mock_get:
            mock_get.side_effect = httpx.ConnectTimeout("Connection timed out")
            
            # ConnectTimeout is caught and converted to NetworkError (per client.py:198-203)
            with pytest.raises(NetworkError):
                client.get("/test")
        
        client.close()
    
    def test_read_timeout(self) -> None:
        """Test handling of read timeout errors."""
        client = APIClient(timeout=5.0, retry_times=1)
        
        with patch.object(client._client, 'get') as mock_get:
            mock_get.side_effect = httpx.ReadTimeout("Read timed out")
            
            with pytest.raises(ClientTimeoutError):
                client.get("/test")
        
        client.close()
    
    def test_timeout_retry_behavior(self) -> None:
        """Test that timeouts trigger retries."""
        client = APIClient(timeout=5.0, retry_times=2)
        
        with patch.object(client._client, 'get') as mock_get:
            mock_get.side_effect = httpx.TimeoutException("Request timed out")
            
            with pytest.raises(ClientTimeoutError):
                client.get("/test")
            
            assert mock_get.call_count == 2
        
        client.close()


class TestHTTPClientStatusErrors:
    """Test HTTP status code error handling."""
    
    def test_404_not_found(self) -> None:
        """Test handling of 404 Not Found responses."""
        client = APIClient(retry_times=1)
        
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 404
        mock_response.text = "Not found"
        
        with patch.object(client._client, 'get') as mock_get:
            mock_get.return_value = mock_response
            
            with pytest.raises(HTTPStatusError) as exc_info:
                client.get("/test")
            
            assert exc_info.value.status_code == 404
        
        client.close()
    
    def test_500_internal_server_error(self) -> None:
        """Test handling of 500 Internal Server Error responses."""
        client = APIClient(retry_times=1)
        
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 500
        mock_response.text = "Internal server error"
        
        with patch.object(client._client, 'get') as mock_get:
            mock_get.return_value = mock_response
            
            with pytest.raises(HTTPStatusError) as exc_info:
                client.get("/test")
            
            assert exc_info.value.status_code == 500
        
        client.close()
    
    def test_429_too_many_requests(self) -> None:
        """Test handling of 429 Too Many Requests."""
        client = APIClient(retry_times=1)
        
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 429
        mock_response.text = "Too many requests"
        
        with patch.object(client._client, 'get') as mock_get:
            mock_get.return_value = mock_response
            
            with pytest.raises(HTTPStatusError) as exc_info:
                client.get("/test")
            
            assert exc_info.value.status_code == 429
        
        client.close()
    
    def test_status_error_no_retry(self) -> None:
        """Test that HTTP status errors are not retried."""
        client = APIClient(retry_times=3)
        
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 400
        mock_response.text = "Bad request"
        
        with patch.object(client._client, 'get') as mock_get:
            mock_get.return_value = mock_response
            
            with pytest.raises(HTTPStatusError):
                client.get("/test")
            
            assert mock_get.call_count == 1
        
        client.close()


class TestHTTPClientJSONErrors:
    """Test JSON parsing error handling."""
    
    def test_invalid_json_response(self) -> None:
        """Test handling of invalid JSON in response."""
        client = APIClient(retry_times=1)
        
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.text = "not valid json {]"
        mock_response.json.side_effect = json.JSONDecodeError("msg", "doc", 0)
        
        with patch.object(client._client, 'get') as mock_get:
            mock_get.return_value = mock_response
            
            with pytest.raises(JSONParseError):
                client.get("/test")
        
        client.close()
    
    def test_empty_response_body(self) -> None:
        """Test handling of empty response body."""
        client = APIClient(retry_times=1)
        
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.text = ""
        mock_response.json.side_effect = json.JSONDecodeError("msg", "doc", 0)
        
        with patch.object(client._client, 'get') as mock_get:
            mock_get.return_value = mock_response
            
            with pytest.raises(JSONParseError):
                client.get("/test")
        
        client.close()


class TestHTTPClientPostRequests:
    """Test POST request handling."""
    
    def test_post_with_json_payload(self) -> None:
        """Test POST request with JSON payload."""
        client = APIClient()
        
        mock_response = Mock(spec=httpx.Response)
        mock_response.status_code = 201
        mock_response.json.return_value = {"id": "123", "status": "created"}
        
        with patch.object(client._client, 'post') as mock_post:
            mock_post.return_value = mock_response
            
            result = client.post("/test", json={"name": "test"})
            
            assert result["id"] == "123"
            assert result["status"] == "created"
            mock_post.assert_called_once()
        
        client.close()
    
    def test_post_network_error_retry(self) -> None:
        """Test POST request retries on network errors."""
        client = APIClient(retry_times=3)
        
        with patch.object(client._client, 'post') as mock_post:
            mock_post.side_effect = httpx.ConnectError("Connection refused")
            
            with pytest.raises(NetworkError):
                client.post("/test", json={"name": "test"})
            
            assert mock_post.call_count == 3
        
        client.close()
    
    def test_post_timeout_error(self) -> None:
        """Test POST request timeout."""
        client = APIClient(timeout=5.0, retry_times=1)
        
        with patch.object(client._client, 'post') as mock_post:
            mock_post.side_effect = httpx.TimeoutException("Request timed out")
            
            with pytest.raises(ClientTimeoutError):
                client.post("/test", json={"name": "test"})
        
        client.close()


class TestHTTPClientErrorMessages:
    """Test user-friendly error messages."""
    
    def test_network_error_message(self) -> None:
        """Test NetworkError provides helpful user message."""
        error = NetworkError("Connection refused")
        msg = error.user_friendly_message()
        
        assert "connect" in msg.lower()
    
    def test_timeout_error_message(self) -> None:
        """Test TimeoutError provides helpful user message."""
        error = ClientTimeoutError("Request timed out")
        msg = error.user_friendly_message()
        
        assert "timeout" in msg.lower()
    
    def test_http_status_error_message(self) -> None:
        """Test HTTPStatusError includes status code."""
        error = HTTPStatusError("Bad request", status_code=400, response_text="Invalid")
        msg = error.user_friendly_message()
        
        assert "400" in msg
    
    def test_json_parse_error_message(self) -> None:
        """Test JSONParseError provides helpful message."""
        error = JSONParseError("Failed to parse", response_text="invalid json")
        msg = error.user_friendly_message()
        
        assert "json" in msg.lower()
