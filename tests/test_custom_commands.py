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

"""Tests for the custom-commands feature."""

import shlex

import pytest
import voluptuous as v

from hubtty.config import ConfigSchema


class TestCustomCommandSchema:
    """Voluptuous schema validation for custom-commands config entries."""

    def _validate(self, data):
        schema = v.Schema(ConfigSchema.custom_commands)
        return schema(data)

    def test_valid_full(self):
        """Accept a fully-specified custom command."""
        data = [{'key': 'meta 1',
                 'command': 'echo {repository}',
                 'description': 'Say hello',
                 'context': ['pull-request', 'diff']}]
        result = self._validate(data)
        assert result[0]['key'] == 'meta 1'
        assert result[0]['context'] == ['pull-request', 'diff']

    def test_valid_minimal(self):
        """Accept a command with only required fields."""
        data = [{'key': 'meta 2', 'command': 'true'}]
        result = self._validate(data)
        assert result[0]['key'] == 'meta 2'
        assert 'description' not in result[0]
        assert 'context' not in result[0]

    def test_all_context_values(self):
        """Accept every valid context name."""
        data = [{'key': 'meta 3', 'command': 'true',
                 'context': ['repository-list', 'pull-request-list',
                             'pull-request', 'diff']}]
        result = self._validate(data)
        assert len(result[0]['context']) == 4

    def test_invalid_context(self):
        """Reject an unknown context name."""
        data = [{'key': 'meta 1', 'command': 'true',
                 'context': ['invalid-screen']}]
        with pytest.raises(v.MultipleInvalid):
            self._validate(data)

    def test_missing_key(self):
        """Reject a command missing the required 'key' field."""
        data = [{'command': 'true'}]
        with pytest.raises(v.MultipleInvalid):
            self._validate(data)

    def test_missing_command(self):
        """Reject a command missing the required 'command' field."""
        data = [{'key': 'meta 1'}]
        with pytest.raises(v.MultipleInvalid):
            self._validate(data)


class TestInterpolation:
    """Variable interpolation and shell-quoting logic."""

    @staticmethod
    def _interpolate(template, context_vars):
        """Reproduce the interpolation logic from App.runCustomCommand."""
        safe_vars = {k: shlex.quote(v) for k, v in context_vars.items()}
        return template.format_map(safe_vars)

    def test_basic(self):
        result = self._interpolate(
            'echo {repository}',
            {'repository': 'owner/repo'})
        assert result == 'echo owner/repo'

    def test_multiple_variables(self):
        result = self._interpolate(
            'gh pr checkout {number} --repo {repository}',
            {'number': '42', 'repository': 'owner/repo'})
        assert result == 'gh pr checkout 42 --repo owner/repo'

    def test_shell_injection_is_quoted(self):
        """Malicious values must be neutralised by shlex.quote."""
        malicious = '"; rm -rf / #'
        result = self._interpolate('echo {title}', {'title': malicious})
        # shlex.quote wraps the value in single quotes
        assert result == "echo '\"; rm -rf / #'"
        # The quoted result must not equal a naive (unquoted) interpolation
        naive = 'echo {title}'.format_map({'title': malicious})
        assert result != naive

    def test_single_quote_in_value(self):
        """Values containing single quotes are still safely quoted."""
        result = self._interpolate(
            'echo {title}',
            {'title': "it's a test"})
        # shlex.quote handles embedded single quotes
        assert 'echo ' in result
        # The value must round-trip safely through a shell
        assert "it's a test" not in result  # raw form must not appear

    def test_missing_variable_raises(self):
        with pytest.raises(KeyError):
            self._interpolate('echo {missing}', {'repository': 'r'})

    def test_empty_value(self):
        result = self._interpolate('echo {branch}', {'branch': ''})
        assert result == "echo ''"


class TestContextRestriction:
    """Context-checking logic from App.runCustomCommand."""

    @staticmethod
    def _is_allowed(cmd_config, context_name):
        """Reproduce the context-restriction check from runCustomCommand."""
        allowed = cmd_config.get('context')
        if allowed is not None and context_name not in allowed:
            return False
        return True

    def test_allowed(self):
        cfg = {'key': 'meta 1', 'command': 'true',
               'context': ['pull-request', 'diff']}
        assert self._is_allowed(cfg, 'pull-request') is True

    def test_blocked(self):
        cfg = {'key': 'meta 1', 'command': 'true',
               'context': ['pull-request']}
        assert self._is_allowed(cfg, 'repository-list') is False

    def test_no_context_means_all_screens(self):
        cfg = {'key': 'meta 1', 'command': 'true'}
        assert self._is_allowed(cfg, 'repository-list') is True
        assert self._is_allowed(cfg, 'pull-request') is True
        assert self._is_allowed(cfg, 'diff') is True

    def test_unknown_screen_blocked_when_restricted(self):
        cfg = {'key': 'meta 1', 'command': 'true',
               'context': ['pull-request']}
        # None represents an unrecognised screen type
        assert self._is_allowed(cfg, None) is False

    def test_empty_context_blocks_all(self):
        cfg = {'key': 'meta 1', 'command': 'true',
               'context': []}
        assert self._is_allowed(cfg, 'pull-request') is False
        assert self._is_allowed(cfg, 'repository-list') is False
