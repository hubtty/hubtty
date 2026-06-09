# Copyright The Hubtty Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""Tests for HTTP client methods."""

import pytest
from unittest.mock import Mock, patch
import json

from hubtty.sync.http import HTTPClient
from hubtty.sync.exceptions import OfflineError, RateLimitError, RestrictedError


@pytest.fixture
def mock_app():
    """Create a mock App instance."""
    app = Mock()
    app.config.api_url = 'https://api.github.com/'
    app.config.token = 'test-token'
    app.error = Mock()
    return app


@pytest.fixture
def http_client(mock_app):
    """Create an HTTPClient for testing."""
    return HTTPClient(mock_app, "TestAgent/1.0", "2022-11-28")


class TestHTTPClientInit:
    """Tests for HTTPClient initialization."""

    def test_init_sets_attributes(self, mock_app):
        """Initialization sets required attributes."""
        client = HTTPClient(mock_app, "TestAgent/1.0", "2022-11-28")
        assert client.app == mock_app
        assert client.user_agent == "TestAgent/1.0"
        assert client.github_api_version == "2022-11-28"

    def test_init_creates_session(self, http_client):
        """Initialization creates a requests session."""
        assert http_client.session is not None
        assert 'Authorization' in http_client.session.headers


class TestHTTPClientURL:
    """Tests for URL construction."""

    def test_url_construction(self, http_client):
        """url() correctly constructs full URL."""
        result = http_client.url('repos/test')
        assert result == 'https://api.github.com/repos/test'


class TestHTTPHeaders:
    """Tests for header handling."""

    def test_base_headers(self, http_client):
        """_base_headers includes required headers."""
        headers = http_client._base_headers()
        assert headers['User-Agent'] == "TestAgent/1.0"
        assert headers['X-GitHub-Api-Version'] == "2022-11-28"


class TestCheckResponse:
    """Tests for response validation."""

    @pytest.mark.parametrize("status_code", [500, 502, 503, 504])
    def test_5xx_raises_offline(self, http_client, status_code):
        """5xx responses raise OfflineError."""
        response = Mock()
        response.status_code = status_code

        with pytest.raises(OfflineError, match=str(status_code)):
            http_client.checkResponse(response)

    def test_403_oauth_restriction_raises_restricted(self, http_client):
        """403 with OAuth restriction message raises RestrictedError."""
        response = Mock()
        response.status_code = 403
        response.text = "the `myorg` organization has enabled OAuth App access restrictions"
        response.headers = {'X-RateLimit-Remaining': '100'}  # Not rate limited

        with pytest.raises(RestrictedError) as exc_info:
            http_client.checkResponse(response)
        assert "myorg" in str(exc_info.value)

    def test_403_oauth_shows_error_to_user(self, http_client, mock_app):
        """403 OAuth restriction shows error to user."""
        response = Mock()
        response.status_code = 403
        response.text = "the `testorg` organization has enabled OAuth App access restrictions"
        response.headers = {'X-RateLimit-Remaining': '100'}  # Not rate limited

        with pytest.raises(RestrictedError):
            http_client.checkResponse(response)

        mock_app.error.assert_called_once()
        call_arg = mock_app.error.call_args[0][0]
        assert "testorg" in call_arg

    def test_403_other_raises_exception(self, http_client):
        """403 without OAuth message raises generic exception."""
        response = Mock()
        response.status_code = 403
        response.text = "Forbidden"
        response.headers = {'X-RateLimit-Remaining': '100'}  # Not rate limited

        with pytest.raises(Exception) as exc_info:
            http_client.checkResponse(response)
        assert "403" in str(exc_info.value)

    def test_404_raises_exception(self, http_client):
        """404 response raises exception."""
        response = Mock()
        response.status_code = 404
        response.text = "Not Found"

        with pytest.raises(Exception) as exc_info:
            http_client.checkResponse(response)
        assert "404" in str(exc_info.value)

    def test_200_ok_passes(self, http_client):
        """200 response passes without exception."""
        response = Mock()
        response.status_code = 200
        http_client.checkResponse(response)  # Should not raise

    def test_201_created_passes(self, http_client):
        """201 response passes without exception."""
        response = Mock()
        response.status_code = 201
        http_client.checkResponse(response)  # Should not raise


class TestHTTPGet:
    """Tests for GET requests."""

    def test_get_simple(self, http_client):
        """GET returns parsed JSON."""
        response = Mock()
        response.status_code = 200
        response.text = '{"id": 1, "name": "test"}'
        response.headers = {'X-RateLimit-Remaining': '100'}
        response.links = {}

        with patch.object(http_client.session, 'get', return_value=response):
            result = http_client.get('repos/test')

        assert result == {"id": 1, "name": "test"}

    def test_get_search_extracts_items(self, http_client):
        """GET with search results extracts 'items' key."""
        response = Mock()
        response.status_code = 200
        response.text = '{"total_count": 2, "items": [{"id": 1}, {"id": 2}]}'
        response.headers = {'X-RateLimit-Remaining': '100'}
        response.links = {}

        with patch.object(http_client.session, 'get', return_value=response):
            result = http_client.get('search/issues')

        assert result == [{"id": 1}, {"id": 2}]

    def test_get_pagination(self, http_client):
        """GET follows pagination links."""
        # First response with 'next' link
        r1 = Mock()
        r1.status_code = 200
        r1.text = '[{"id": 1}]'
        r1.headers = {'X-RateLimit-Remaining': '100'}
        r1.links = {'next': {'url': 'https://api.github.com/page2'}}

        # Second response without 'next' link
        r2 = Mock()
        r2.status_code = 200
        r2.text = '[{"id": 2}]'
        r2.headers = {'X-RateLimit-Remaining': '99'}
        r2.links = {}

        with patch.object(http_client.session, 'get', side_effect=[r1, r2]):
            result = http_client.get('repos/test')

        assert len(result) == 2
        assert result[0]['id'] == 1
        assert result[1]['id'] == 2

    def test_get_custom_headers(self, http_client):
        """GET includes custom headers."""
        response = Mock()
        response.status_code = 200
        response.text = '{}'
        response.headers = {'X-RateLimit-Remaining': '100'}
        response.links = {}

        with patch.object(http_client.session, 'get', return_value=response) as mock_get:
            http_client.get('repos/test', headers={'X-Custom': 'value'})

        call_kwargs = mock_get.call_args.kwargs
        assert call_kwargs['headers']['X-Custom'] == 'value'

    def test_get_rate_limit_wait(self, http_client):
        """GET waits when rate limited with reset time."""
        import time

        r1 = Mock()
        r1.status_code = 200
        r1.text = '{"id": 1}'
        r1.headers = {
            'X-RateLimit-Remaining': '0',
            'X-RateLimit-Reset': str(int(time.time()) + 1)
        }
        r1.links = {}

        r2 = Mock()
        r2.status_code = 200
        r2.text = '{"id": 1}'
        r2.headers = {'X-RateLimit-Remaining': '100'}
        r2.links = {}

        with patch.object(http_client.session, 'get', side_effect=[r1, r2]):
            with patch('hubtty.sync.http.time.sleep') as mock_sleep:
                http_client.get('repos/test')

        mock_sleep.assert_called_once()

    def test_get_rate_limit_no_reset_waits_60s(self, http_client):
        """GET waits 60s when rate limited without reset time (secondary rate limit fallback)."""
        # First response: rate limited with no reset time
        r1 = Mock()
        r1.status_code = 200
        r1.text = '{"id": 1}'
        r1.headers = {'X-RateLimit-Remaining': '0'}
        r1.links = {}

        # Second response: success after waiting
        r2 = Mock()
        r2.status_code = 200
        r2.text = '{"id": 1}'
        r2.headers = {'X-RateLimit-Remaining': '100'}
        r2.links = {}

        with patch.object(http_client.session, 'get', side_effect=[r1, r2]):
            with patch('hubtty.sync.http.time.sleep') as mock_sleep:
                http_client.get('repos/test')

        # Should sleep for 60 seconds (GitHub's recommended minimum)
        mock_sleep.assert_called_once_with(60)

    def test_get_handles_429_with_retry_after(self, http_client):
        """GET handles 429 with Retry-After header."""
        # First response: 429 with retry-after
        r1 = Mock()
        r1.status_code = 429
        r1.text = '{"message": "API rate limit exceeded"}'
        r1.headers = {'Retry-After': '30', 'X-RateLimit-Remaining': '0'}
        r1.links = {}
        r1.url = 'https://api.github.com/repos/test'

        # Second response: success
        r2 = Mock()
        r2.status_code = 200
        r2.text = '{"id": 1}'
        r2.headers = {'X-RateLimit-Remaining': '100'}
        r2.links = {}

        with patch.object(http_client.session, 'get', side_effect=[r1, r2]):
            with patch('hubtty.sync.http.time.sleep') as mock_sleep:
                result = http_client.get('repos/test')

        # Should use retry-after value
        mock_sleep.assert_called_once_with(30)
        assert result == {"id": 1}

    def test_get_handles_429_with_reset_time(self, http_client):
        """GET handles 429 with X-RateLimit-Reset header."""
        import time

        reset_time = int(time.time()) + 45

        # First response: 429 with reset time
        r1 = Mock()
        r1.status_code = 429
        r1.text = '{"message": "API rate limit exceeded"}'
        r1.headers = {
            'X-RateLimit-Reset': str(reset_time),
            'X-RateLimit-Remaining': '0',
        }
        r1.links = {}
        r1.url = 'https://api.github.com/repos/test'

        # Second response: success
        r2 = Mock()
        r2.status_code = 200
        r2.text = '{"id": 1}'
        r2.headers = {'X-RateLimit-Remaining': '100'}
        r2.links = {}

        with patch.object(http_client.session, 'get', side_effect=[r1, r2]):
            with patch('hubtty.sync.http.time.sleep') as mock_sleep:
                with patch('hubtty.sync.http.time.time', return_value=time.time()):
                    result = http_client.get('repos/test')

        # Should sleep until reset time (at least 1 second due to max())
        assert mock_sleep.called
        sleep_duration = mock_sleep.call_args[0][0]
        assert sleep_duration >= 1
        assert result == {"id": 1}

    def test_get_handles_403_rate_limit(self, http_client):
        """GET handles 403 with X-RateLimit-Remaining: 0 as rate limit."""
        import time

        reset_time = int(time.time()) + 30

        # First response: 403 with rate limit headers
        r1 = Mock()
        r1.status_code = 403
        r1.text = '{"message": "API rate limit exceeded"}'
        r1.headers = {
            'X-RateLimit-Remaining': '0',
            'X-RateLimit-Reset': str(reset_time),
        }
        r1.links = {}
        r1.url = 'https://api.github.com/repos/test'

        # Second response: success
        r2 = Mock()
        r2.status_code = 200
        r2.text = '{"id": 1}'
        r2.headers = {'X-RateLimit-Remaining': '100'}
        r2.links = {}

        with patch.object(http_client.session, 'get', side_effect=[r1, r2]):
            with patch('hubtty.sync.http.time.sleep') as mock_sleep:
                result = http_client.get('repos/test')

        # Should handle as rate limit, not OAuth restriction
        assert mock_sleep.called
        assert result == {"id": 1}

    def test_get_secondary_rate_limit_without_headers(self, http_client):
        """GET handles secondary rate limit with no timing headers."""
        # First response: 429 with no timing headers
        r1 = Mock()
        r1.status_code = 429
        r1.text = '{"message": "You have exceeded a secondary rate limit"}'
        r1.headers = {}
        r1.links = {}
        r1.url = 'https://api.github.com/repos/test'

        # Second response: success
        r2 = Mock()
        r2.status_code = 200
        r2.text = '{"id": 1}'
        r2.headers = {'X-RateLimit-Remaining': '100'}
        r2.links = {}

        with patch.object(http_client.session, 'get', side_effect=[r1, r2]):
            with patch('hubtty.sync.http.time.sleep') as mock_sleep:
                result = http_client.get('repos/test')

        # Should wait 60 seconds (GitHub's minimum for secondary limits)
        mock_sleep.assert_called_once_with(60)
        assert result == {"id": 1}

    def test_checkResponse_handles_429(self, http_client):
        """checkResponse raises RateLimitError with attributes for 429."""
        response = Mock()
        response.status_code = 429
        response.text = '{"message": "API rate limit exceeded"}'
        response.headers = {
            'Retry-After': '45',
            'X-RateLimit-Remaining': '0',
            'X-RateLimit-Reset': '1234567890',
        }
        response.url = 'https://api.github.com/repos/test'

        with pytest.raises(RateLimitError) as exc_info:
            http_client.checkResponse(response)

        error = exc_info.value
        assert error.retry_after == 45
        assert error.reset_time == 1234567890
        assert error.remaining == 0
        assert error.url == 'https://api.github.com/repos/test'
        assert error.is_secondary  # Has retry-after, so it's secondary

    def test_rate_limit_error_attributes(self):
        """RateLimitError stores all context correctly."""
        error = RateLimitError(
            'Test rate limit',
            reset_time=1234567890,
            retry_after=60,
            remaining=0,
            is_secondary=True,
            url='https://api.github.com/test',
        )

        assert str(error) == 'Test rate limit'
        assert error.reset_time == 1234567890
        assert error.retry_after == 60
        assert error.remaining == 0
        assert error.is_secondary is True
        assert error.url == 'https://api.github.com/test'

    def test_negative_sleep_prevention(self, http_client):
        """GET prevents negative sleep from clock skew."""
        import time

        # Reset time in the past (clock skew scenario)
        reset_time = int(time.time()) - 10

        # First response: rate limited with reset time in past
        r1 = Mock()
        r1.status_code = 200
        r1.text = '{"id": 1}'
        r1.headers = {
            'X-RateLimit-Remaining': '0',
            'X-RateLimit-Reset': str(reset_time),
        }
        r1.links = {}

        # Second response: success
        r2 = Mock()
        r2.status_code = 200
        r2.text = '{"id": 1}'
        r2.headers = {'X-RateLimit-Remaining': '100'}
        r2.links = {}

        with patch.object(http_client.session, 'get', side_effect=[r1, r2]):
            with patch('hubtty.sync.http.time.sleep') as mock_sleep:
                http_client.get('repos/test')

        # Should sleep for at least 1 second (not negative)
        assert mock_sleep.called
        sleep_duration = mock_sleep.call_args[0][0]
        assert sleep_duration >= 1


class TestHTTPPost:
    """Tests for POST requests."""

    def test_post_sends_json(self, http_client):
        """POST sends JSON-encoded body."""
        response = Mock()
        response.status_code = 201
        response.text = '{"success": true}'

        with patch.object(http_client.session, 'post', return_value=response) as mock_post:
            result = http_client.post('repos/test', {'key': 'value'})

        call_kwargs = mock_post.call_args.kwargs
        sent_data = json.loads(call_kwargs['data'])
        assert sent_data == {'key': 'value'}
        assert result == {"success": True}

    def test_post_includes_accept_header(self, http_client):
        """POST includes Accept header."""
        response = Mock()
        response.status_code = 201
        response.text = '{}'

        with patch.object(http_client.session, 'post', return_value=response) as mock_post:
            http_client.post('repos/test', {})

        call_kwargs = mock_post.call_args.kwargs
        assert 'Accept' in call_kwargs['headers']

    def test_post_empty_response(self, http_client):
        """POST with empty response returns None."""
        response = Mock()
        response.status_code = 201
        response.text = ''

        with patch.object(http_client.session, 'post', return_value=response):
            result = http_client.post('repos/test', {})

        assert result is None

    def test_post_handles_rate_limit_with_retry(self, http_client):
        """POST retries when rate limited."""
        import time

        reset_time = int(time.time()) + 30

        # First response: rate limited
        r1 = Mock()
        r1.status_code = 429
        r1.text = '{"message": "API rate limit exceeded"}'
        r1.headers = {
            'X-RateLimit-Remaining': '0',
            'X-RateLimit-Reset': str(reset_time),
        }
        r1.url = 'https://api.github.com/repos/test'

        # Second response: success
        r2 = Mock()
        r2.status_code = 201
        r2.text = '{"id": 123}'
        r2.headers = {'X-RateLimit-Remaining': '100'}

        with patch.object(http_client.session, 'post', side_effect=[r1, r2]):
            with patch('hubtty.sync.http.time.sleep') as mock_sleep:
                result = http_client.post('repos/test', {'key': 'value'})

        # Should have slept and retried
        assert mock_sleep.called
        assert result == {"id": 123}

    def test_post_rate_limit_max_retries(self, http_client):
        """POST gives up after max retries on rate limit."""
        import time

        reset_time = int(time.time()) + 30

        # All responses: rate limited
        r = Mock()
        r.status_code = 429
        r.text = '{"message": "API rate limit exceeded"}'
        r.headers = {'X-RateLimit-Remaining': '0', 'X-RateLimit-Reset': str(reset_time)}
        r.url = 'https://api.github.com/repos/test'

        with patch.object(http_client.session, 'post', return_value=r):
            with patch('hubtty.sync.http.time.sleep'):
                with pytest.raises(RateLimitError):
                    http_client.post('repos/test', {'key': 'value'})


class TestHTTPPut:
    """Tests for PUT requests."""

    def test_put_sends_json(self, http_client):
        """PUT sends JSON-encoded body."""
        response = Mock()
        response.status_code = 200
        response.text = ''
        response.headers = {'X-RateLimit-Remaining': '100'}

        with patch.object(http_client.session, 'put', return_value=response) as mock_put:
            http_client.put('repos/test', {'key': 'value'})

        call_kwargs = mock_put.call_args.kwargs
        sent_data = json.loads(call_kwargs['data'])
        assert sent_data == {'key': 'value'}

    def test_put_returns_none(self, http_client):
        """PUT returns None."""
        response = Mock()
        response.status_code = 200
        response.text = '{"ignored": true}'
        response.headers = {'X-RateLimit-Remaining': '100'}

        with patch.object(http_client.session, 'put', return_value=response):
            result = http_client.put('repos/test', {})

        assert result is None


class TestHTTPPatch:
    """Tests for PATCH requests."""

    def test_patch_sends_json(self, http_client):
        """PATCH sends JSON-encoded body."""
        response = Mock()
        response.status_code = 200
        response.text = ''
        response.headers = {'X-RateLimit-Remaining': '100'}

        with patch.object(http_client.session, 'patch', return_value=response) as mock_patch:
            http_client.patch('repos/test', {'key': 'value'})

        call_kwargs = mock_patch.call_args.kwargs
        sent_data = json.loads(call_kwargs['data'])
        assert sent_data == {'key': 'value'}


class TestHTTPDelete:
    """Tests for DELETE requests."""

    def test_delete_sends_json(self, http_client):
        """DELETE sends JSON-encoded body."""
        response = Mock()
        response.status_code = 200
        response.text = ''
        response.headers = {'X-RateLimit-Remaining': '100'}

        with patch.object(http_client.session, 'delete', return_value=response) as mock_delete:
            http_client.delete('repos/test', {'key': 'value'})

        call_kwargs = mock_delete.call_args.kwargs
        sent_data = json.loads(call_kwargs['data'])
        assert sent_data == {'key': 'value'}


class TestQuery:
    """Tests for query method."""

    def test_query_calls_get(self, http_client):
        """query() calls get with correct path."""
        with patch.object(http_client, 'get', return_value=[]) as mock_get:
            http_client.query('type:pr state:open')

        mock_get.assert_called_once()
        call_arg = mock_get.call_args[0][0]
        assert 'search/issues' in call_arg
        assert 'type:pr' in call_arg


class TestETagSupport:
    """Tests for ETag / conditional request support."""

    def test_etag_disabled_by_default(self, http_client):
        """use_etag defaults to False; no If-None-Match header."""
        response = Mock()
        response.status_code = 200
        response.text = '{"id": 1}'
        response.headers = {'X-RateLimit-Remaining': '100'}
        response.links = {}

        with patch.object(http_client.session, 'get',
                          return_value=response) as mock_get:
            http_client.get('repos/test')

        sent_headers = mock_get.call_args.kwargs['headers']
        assert 'If-None-Match' not in sent_headers

    def test_etag_first_request_no_cache(self, http_client):
        """First request with use_etag=True has no If-None-Match."""
        response = Mock()
        response.status_code = 200
        response.text = '{"id": 1}'
        response.headers = {
            'X-RateLimit-Remaining': '100',
            'ETag': '"abc123"',
        }
        response.links = {}

        with patch.object(http_client.session, 'get',
                          return_value=response) as mock_get:
            result = http_client.get('repos/test', use_etag=True)

        sent_headers = mock_get.call_args.kwargs['headers']
        assert 'If-None-Match' not in sent_headers
        assert result == {"id": 1}

    def test_etag_cached_after_first_request(self, http_client):
        """ETag and response are cached after a 200 with use_etag."""
        response = Mock()
        response.status_code = 200
        response.text = '{"id": 1}'
        response.headers = {
            'X-RateLimit-Remaining': '100',
            'ETag': '"abc123"',
        }
        response.links = {}

        with patch.object(http_client.session, 'get',
                          return_value=response):
            http_client.get('repos/test', use_etag=True)

        assert 'repos/test' in http_client._etag_cache
        etag, cached = http_client._etag_cache['repos/test']
        assert etag == '"abc123"'
        assert cached == {"id": 1}

    def test_etag_304_returns_cached_data(self, http_client):
        """304 Not Modified returns previously cached data."""
        # Seed the cache
        http_client._etag_cache['repos/test'] = (
            '"abc123"', {"id": 1, "cached": True}
        )

        response = Mock()
        response.status_code = 304
        response.headers = {'X-RateLimit-Remaining': '100'}
        response.links = {}

        with patch.object(http_client.session, 'get',
                          return_value=response) as mock_get:
            result = http_client.get('repos/test', use_etag=True)

        assert result == {"id": 1, "cached": True}
        # Verify If-None-Match was sent
        sent_headers = mock_get.call_args.kwargs['headers']
        assert sent_headers['If-None-Match'] == '"abc123"'

    def test_etag_200_updates_cache(self, http_client):
        """200 after a cached ETag updates the cache."""
        # Seed the cache with old data
        http_client._etag_cache['repos/test'] = (
            '"old-etag"', {"id": 1}
        )

        response = Mock()
        response.status_code = 200
        response.text = '{"id": 2, "updated": true}'
        response.headers = {
            'X-RateLimit-Remaining': '100',
            'ETag': '"new-etag"',
        }
        response.links = {}

        with patch.object(http_client.session, 'get',
                          return_value=response):
            result = http_client.get('repos/test', use_etag=True)

        assert result == {"id": 2, "updated": True}
        etag, cached = http_client._etag_cache['repos/test']
        assert etag == '"new-etag"'
        assert cached == {"id": 2, "updated": True}

    def test_etag_not_sent_when_disabled(self, http_client):
        """If-None-Match not sent when use_etag=False even with cache."""
        http_client._etag_cache['repos/test'] = (
            '"abc123"', {"id": 1}
        )

        response = Mock()
        response.status_code = 200
        response.text = '{"id": 2}'
        response.headers = {'X-RateLimit-Remaining': '100'}
        response.links = {}

        with patch.object(http_client.session, 'get',
                          return_value=response) as mock_get:
            result = http_client.get('repos/test', use_etag=False)

        sent_headers = mock_get.call_args.kwargs['headers']
        assert 'If-None-Match' not in sent_headers
        assert result == {"id": 2}

    def test_etag_pagination_caches_full_result(self, http_client):
        """ETag from first page caches the full paginated result."""
        r1 = Mock()
        r1.status_code = 200
        r1.text = '[{"id": 1}]'
        r1.headers = {
            'X-RateLimit-Remaining': '100',
            'ETag': '"page1-etag"',
        }
        r1.links = {'next': {'url': 'https://api.github.com/page2'}}

        r2 = Mock()
        r2.status_code = 200
        r2.text = '[{"id": 2}]'
        r2.headers = {'X-RateLimit-Remaining': '99'}
        r2.links = {}

        with patch.object(http_client.session, 'get', side_effect=[r1, r2]):
            result = http_client.get('repos/test', use_etag=True)

        assert result == [{"id": 1}, {"id": 2}]
        etag, cached = http_client._etag_cache['repos/test']
        assert etag == '"page1-etag"'
        assert cached == [{"id": 1}, {"id": 2}]

    def test_etag_pagination_304_returns_full_cached(self, http_client):
        """304 on paginated endpoint returns full cached result."""
        http_client._etag_cache['repos/test'] = (
            '"page1-etag"', [{"id": 1}, {"id": 2}]
        )

        response = Mock()
        response.status_code = 304
        response.headers = {'X-RateLimit-Remaining': '100'}
        response.links = {}

        with patch.object(http_client.session, 'get',
                          return_value=response):
            result = http_client.get('repos/test', use_etag=True)

        # Returns full cached result (both pages)
        assert result == [{"id": 1}, {"id": 2}]

    def test_etag_pagination_no_etag_on_subsequent_pages(self, http_client):
        """If-None-Match is only sent on the first page."""
        http_client._etag_cache['repos/test'] = (
            '"old-etag"', [{"id": 0}]
        )

        r1 = Mock()
        r1.status_code = 200
        r1.text = '[{"id": 1}]'
        r1.headers = {
            'X-RateLimit-Remaining': '100',
            'ETag': '"new-etag"',
        }
        r1.links = {'next': {'url': 'https://api.github.com/page2'}}

        r2 = Mock()
        r2.status_code = 200
        r2.text = '[{"id": 2}]'
        r2.headers = {'X-RateLimit-Remaining': '99'}
        r2.links = {}

        with patch.object(http_client.session, 'get',
                          side_effect=[r1, r2]) as mock_get:
            http_client.get('repos/test', use_etag=True)

        # First call has If-None-Match
        first_headers = mock_get.call_args_list[0].kwargs['headers']
        assert first_headers['If-None-Match'] == '"old-etag"'
        # Second call does NOT have If-None-Match
        second_headers = mock_get.call_args_list[1].kwargs['headers']
        assert 'If-None-Match' not in second_headers

    def test_etag_no_etag_header_in_response(self, http_client):
        """Response without ETag header does not cache."""
        response = Mock()
        response.status_code = 200
        response.text = '{"id": 1}'
        response.headers = {'X-RateLimit-Remaining': '100'}
        response.links = {}

        with patch.object(http_client.session, 'get',
                          return_value=response):
            http_client.get('repos/test', use_etag=True)

        assert 'repos/test' not in http_client._etag_cache

    def test_etag_different_paths_independent(self, http_client):
        """Different paths have independent cache entries."""
        r1 = Mock()
        r1.status_code = 200
        r1.text = '{"branch": "main"}'
        r1.headers = {
            'X-RateLimit-Remaining': '100',
            'ETag': '"etag-branches"',
        }
        r1.links = {}

        r2 = Mock()
        r2.status_code = 200
        r2.text = '[{"name": "bug"}]'
        r2.headers = {
            'X-RateLimit-Remaining': '99',
            'ETag': '"etag-labels"',
        }
        r2.links = {}

        with patch.object(http_client.session, 'get', return_value=r1):
            http_client.get('repos/test/branches', use_etag=True)
        with patch.object(http_client.session, 'get', return_value=r2):
            http_client.get('repos/test/labels', use_etag=True)

        assert len(http_client._etag_cache) == 2
        assert http_client._etag_cache['repos/test/branches'][0] == '"etag-branches"'
        assert http_client._etag_cache['repos/test/labels'][0] == '"etag-labels"'

    def test_etag_cache_empty_on_init(self, http_client):
        """ETag cache starts empty."""
        assert http_client._etag_cache == {}
