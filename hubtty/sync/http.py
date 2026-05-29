# Copyright 2014 OpenStack Foundation
# Copyright 2014 Hewlett-Packard Development Company, L.P.
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

"""HTTP client for GitHub API communication."""

import json
import logging
import re
import time
from typing import Any, Callable, Dict, Optional, TYPE_CHECKING

import requests

from .constants import TIMEOUT
from .exceptions import OfflineError, RestrictedError, RateLimitError

if TYPE_CHECKING:
    from hubtty.app import App


class HTTPClient:
    """Handles all HTTP communication with the GitHub API.

    This class provides methods for GET, POST, PUT, PATCH, and DELETE requests,
    with automatic pagination, rate limit handling, and response validation.
    """

    def __init__(self, app: 'App', user_agent: str, github_api_version: str) -> None:
        """Initialize the HTTP client.

        Args:
            app: The main application instance.
            user_agent: User-Agent string for HTTP requests.
            github_api_version: GitHub API version string.
        """
        self.app = app
        self.user_agent = user_agent
        self.github_api_version = github_api_version
        self.session = requests.Session()
        self.session.headers.update({'Authorization': 'token ' + app.config.token})
        self.log = logging.getLogger('hubtty.sync')

    def url(self, path: str) -> str:
        """Convert a path to a full URL.

        Args:
            path: API path (e.g., 'repos/owner/repo/pulls').

        Returns:
            Full URL including the API base.
        """
        return self.app.config.api_url + path

    def _base_headers(self) -> Dict[str, str]:
        """Return base headers for all requests."""
        return {
            'User-Agent': self.user_agent,
            'X-GitHub-Api-Version': self.github_api_version,
        }

    def checkResponse(self, response: requests.Response) -> None:
        """Validate an HTTP response and raise appropriate exceptions.

        Args:
            response: The HTTP response to check.

        Raises:
            OfflineError: If the server returned 503.
            RestrictedError: If OAuth app restrictions block access.
            Exception: For other 4xx/5xx status codes.
        """
        self.log.debug('HTTP status code: %d', response.status_code)
        if response.status_code == 503:
            raise OfflineError("Received 503 status code")
        elif response.status_code == 403:
            result = re.search(
                r"the `([\w-]+)` organization has enabled OAuth App access restrictions",
                response.text
            )
            if result:
                org = result.group(1)
                error_msg = (
                    f"The '{org}' organization has enabled third-party restrictions "
                    f"and has not yet approved Hubtty. Your review will be submitted "
                    f"again next time Hubtty starts. Create yourself a Personal Access "
                    f"Token to continue using Hubtty with this organization: "
                    f"https://hubtty.readthedocs.io/en/latest/authentication.html"
                )
                self.app.error(error_msg)
                raise RestrictedError(
                    f"The '{org}' organization has enabled third-party restrictions "
                    f"and has not yet approved hubtty"
                )
            else:
                raise Exception(
                    f"Received {response.status_code} status code: {response.text}"
                )
        elif response.status_code >= 400:
            raise Exception(
                f"Received {response.status_code} status code: {response.text}"
            )

    def get(
        self,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        response_callback: Optional[Callable[[requests.Response], None]] = None,
    ) -> Any:
        """Perform a GET request with automatic pagination.

        Args:
            path: API path to request.
            headers: Additional headers to include.
            response_callback: Custom response validator (defaults to checkResponse).

        Returns:
            Parsed JSON response, or list of results if paginated.
        """
        url = self.url(path)
        ret = None
        done = False

        default_headers = {
            **self._base_headers(),
            'Accept': 'application/vnd.github.v3+json',
            'Accept-Encoding': 'gzip',
        }

        if not response_callback:
            response_callback = self.checkResponse

        while not done:
            self.log.debug('GET: %s', url)

            r = self.session.get(
                url,
                timeout=TIMEOUT,
                headers={**default_headers, **(headers or {})}
            )
            response_callback(r)

            if int(r.headers.get('X-RateLimit-Remaining', 1)) < 1:
                if r.headers.get('X-RateLimit-Reset'):
                    sleep = int(r.headers.get('X-RateLimit-Reset')) - int(time.time())
                    self.log.debug('Hit rate limit, retrying in %d seconds', sleep)
                    time.sleep(sleep)
                    continue
                else:
                    raise RateLimitError("Hitting RateLimit")

            if r.status_code == 200:
                result = json.loads(r.text)
                # Search queries store results under the 'items' key
                if isinstance(result, dict) and 'items' in result:
                    result = result.get('items', [])
                if isinstance(ret, list):
                    ret.extend(result)
                else:
                    ret = result
                if len(result) if isinstance(result, list) else result:
                    self.log.debug('200 OK, Received: %s', result)
                else:
                    self.log.debug('200 OK, No body.')

            if 'next' in r.links.keys():
                url = r.links['next']['url']
            else:
                done = True

        return ret

    def _mutating_request(
        self,
        method: str,
        path: str,
        data: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
        response_callback: Optional[Callable[[requests.Response], None]] = None,
        include_accept: bool = False,
    ) -> Optional[Any]:
        """Perform a mutating HTTP request (POST, PUT, PATCH, DELETE).

        Args:
            method: HTTP method ('post', 'put', 'patch', 'delete').
            path: API path to request.
            data: Request body data.
            headers: Additional headers to include.
            response_callback: Custom response validator.
            include_accept: Whether to include Accept header.

        Returns:
            Parsed JSON response for POST, None for other methods.
        """
        url = self.url(path)
        default_headers = {
            **self._base_headers(),
            'Content-Type': 'application/json;charset=UTF-8',
        }
        if include_accept:
            default_headers['Accept'] = 'application/vnd.github.v3+json'

        if not response_callback:
            response_callback = self.checkResponse

        self.log.debug('%s: %s', method.upper(), url)
        self.log.debug('data: %s', data)

        request_method = getattr(self.session, method)
        r = request_method(
            url,
            data=json.dumps(data).encode('utf8'),
            timeout=TIMEOUT,
            headers={**default_headers, **(headers or {})}
        )
        response_callback(r)
        self.log.debug('Received: %s', r.text)

        # Only POST returns parsed response
        if method == 'post' and r.text and len(r.text) > 0:
            try:
                return json.loads(r.text)
            except Exception:
                self.log.exception(
                    "Unable to parse result %s from post to %s", r.text, url
                )
                raise
        return None

    def post(
        self,
        path: str,
        data: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
        response_callback: Optional[Callable[[requests.Response], None]] = None,
    ) -> Optional[Any]:
        """Perform a POST request.

        Args:
            path: API path to request.
            data: Request body data.
            headers: Additional headers to include.
            response_callback: Custom response validator.

        Returns:
            Parsed JSON response.
        """
        return self._mutating_request(
            'post', path, data, headers, response_callback, include_accept=True
        )

    def put(
        self,
        path: str,
        data: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
        response_callback: Optional[Callable[[requests.Response], None]] = None,
    ) -> None:
        """Perform a PUT request.

        Args:
            path: API path to request.
            data: Request body data.
            headers: Additional headers to include.
            response_callback: Custom response validator.
        """
        self._mutating_request('put', path, data, headers, response_callback)

    def patch(
        self,
        path: str,
        data: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
        response_callback: Optional[Callable[[requests.Response], None]] = None,
    ) -> None:
        """Perform a PATCH request.

        Args:
            path: API path to request.
            data: Request body data.
            headers: Additional headers to include.
            response_callback: Custom response validator.
        """
        self._mutating_request('patch', path, data, headers, response_callback)

    def delete(
        self,
        path: str,
        data: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
        response_callback: Optional[Callable[[requests.Response], None]] = None,
    ) -> None:
        """Perform a DELETE request.

        Args:
            path: API path to request.
            data: Request body data.
            headers: Additional headers to include.
            response_callback: Custom response validator.
        """
        self._mutating_request('delete', path, data, headers, response_callback)

    def query(self, query: str) -> Any:
        """Execute a GitHub search query.

        Args:
            query: Search query string.

        Returns:
            List of search results.
        """
        q = f'search/issues?per_page=100&q={query}'
        self.log.debug('Query: %s', q)
        return self.get(q)
