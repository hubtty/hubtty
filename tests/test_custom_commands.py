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

import queue
import shlex
import signal
import subprocess
import types
from unittest import mock

import pytest
import voluptuous as v

from hubtty.app import App
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

    def test_valid_show_output(self):
        """Accept a command with show-output enabled."""
        data = [{'key': 'meta 1',
                 'command': 'git -C {repo_path} checkout {sha}',
                 'show-output': True}]
        result = self._validate(data)
        assert result[0]['show-output'] is True

    def test_show_output_false(self):
        """Accept show-output set to False."""
        data = [{'key': 'meta 1',
                 'command': 'true',
                 'show-output': False}]
        result = self._validate(data)
        assert result[0]['show-output'] is False

    def test_show_output_rejects_non_bool(self):
        """Reject a non-boolean show-output value."""
        data = [{'key': 'meta 1',
                 'command': 'true',
                 'show-output': 'yes'}]
        with pytest.raises(v.MultipleInvalid):
            self._validate(data)

    def test_show_output_optional(self):
        """show-output is optional and absent by default."""
        data = [{'key': 'meta 1', 'command': 'true'}]
        result = self._validate(data)
        assert 'show-output' not in result[0]

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

    def test_repo_path_variable(self):
        """The repo_path variable is usable in command templates."""
        result = self._interpolate(
            'git -C {repo_path} checkout {sha}',
            {'repo_path': '/home/user/git/owner/repo',
             'sha': 'abc1234'})
        assert result == 'git -C /home/user/git/owner/repo checkout abc1234'

    def test_repo_path_with_spaces(self):
        """repo_path with spaces is safely quoted."""
        result = self._interpolate(
            'git -C {repo_path} status',
            {'repo_path': '/home/user/my repos/owner/repo'})
        assert "'" in result  # shlex.quote wraps in single quotes

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


class TestShowOutputRouting:
    """Verify show-output flag routes to foreground vs background."""

    @staticmethod
    def _should_run_foreground(cmd_config):
        """Reproduce the routing logic from App.runCustomCommand."""
        return bool(cmd_config.get('show-output'))

    def test_show_output_true_is_foreground(self):
        cfg = {'key': 'c', 'command': 'git checkout {sha}',
               'show-output': True}
        assert self._should_run_foreground(cfg) is True

    def test_show_output_false_is_background(self):
        cfg = {'key': 'c', 'command': 'notify-send hi',
               'show-output': False}
        assert self._should_run_foreground(cfg) is False

    def test_show_output_absent_is_background(self):
        cfg = {'key': 'c', 'command': 'notify-send hi'}
        assert self._should_run_foreground(cfg) is False


class TestTimeoutSchema:
    """Schema validation for the timeout field."""

    def _validate(self, data):
        schema = v.Schema(ConfigSchema.custom_commands)
        return schema(data)

    def test_timeout_accepts_positive_int(self):
        data = [{'key': 'meta 1', 'command': 'true', 'timeout': 60}]
        result = self._validate(data)
        assert result[0]['timeout'] == 60

    def test_timeout_rejects_string(self):
        data = [{'key': 'meta 1', 'command': 'true', 'timeout': 'abc'}]
        with pytest.raises(v.MultipleInvalid):
            self._validate(data)

    def test_timeout_rejects_zero(self):
        data = [{'key': 'meta 1', 'command': 'true', 'timeout': 0}]
        with pytest.raises(v.MultipleInvalid):
            self._validate(data)

    def test_timeout_rejects_negative(self):
        data = [{'key': 'meta 1', 'command': 'true', 'timeout': -5}]
        with pytest.raises(v.MultipleInvalid):
            self._validate(data)


class TestForegroundCommandWorker:
    """Integration tests for App._runCustomCommandWorker."""

    @staticmethod
    def _make_harness():
        """Create a minimal stand-in with the attributes the worker needs."""
        obj = types.SimpleNamespace()
        obj.custom_cmd_queue = queue.Queue()
        obj.custom_cmd_pipe = 99  # dummy fd
        return obj

    @mock.patch('hubtty.app.os.write')
    @mock.patch('hubtty.app.subprocess.Popen')
    def test_success(self, mock_popen, mock_write):
        proc = mock_popen.return_value
        proc.communicate.return_value = (b'hello world\n', None)
        proc.returncode = 0

        harness = self._make_harness()
        App._runCustomCommandWorker(harness, 'echo hi', 'Test cmd', timeout=30)

        title, message = harness.custom_cmd_queue.get_nowait()
        assert title == 'Test cmd'
        assert 'hello world' in message
        mock_write.assert_called_once_with(99, b'result\n')

    @mock.patch('hubtty.app.os.write')
    @mock.patch('hubtty.app.subprocess.Popen')
    def test_failure_exit_code(self, mock_popen, mock_write):
        proc = mock_popen.return_value
        proc.communicate.return_value = (b'error occurred\n', None)
        proc.returncode = 1

        harness = self._make_harness()
        App._runCustomCommandWorker(harness, 'false', 'Failing cmd', timeout=30)

        title, message = harness.custom_cmd_queue.get_nowait()
        assert '(exit 1)' in title
        assert 'error occurred' in message

    @mock.patch('hubtty.app.os.write')
    @mock.patch('hubtty.app.os.killpg')
    @mock.patch('hubtty.app.subprocess.Popen')
    def test_timeout_sends_sigterm(self, mock_popen, mock_killpg, mock_write):
        proc = mock_popen.return_value
        proc.pid = 12345
        proc.communicate.side_effect = [
            subprocess.TimeoutExpired('cmd', 5),
            (b'partial output', None),
        ]

        harness = self._make_harness()
        App._runCustomCommandWorker(harness, 'sleep 100', 'Slow cmd', timeout=5)

        mock_killpg.assert_called_with(12345, signal.SIGTERM)
        title, message = harness.custom_cmd_queue.get_nowait()
        assert '(timed out)' in title
        assert 'did not complete within 5' in message
        assert 'partial output' in message

    @mock.patch('hubtty.app.os.write')
    @mock.patch('hubtty.app.os.killpg')
    @mock.patch('hubtty.app.subprocess.Popen')
    def test_timeout_escalates_to_sigkill(self, mock_popen, mock_killpg,
                                          mock_write):
        proc = mock_popen.return_value
        proc.pid = 12345
        proc.communicate.side_effect = [
            subprocess.TimeoutExpired('cmd', 5),
            subprocess.TimeoutExpired('cmd', 5),
            (b'', None),
        ]

        harness = self._make_harness()
        App._runCustomCommandWorker(harness, 'sleep 100', 'Stubborn cmd',
                                    timeout=5)

        assert mock_killpg.call_count == 2
        mock_killpg.assert_any_call(12345, signal.SIGTERM)
        mock_killpg.assert_any_call(12345, signal.SIGKILL)
        title, message = harness.custom_cmd_queue.get_nowait()
        assert '(timed out)' in title

    @mock.patch('hubtty.app.os.write')
    @mock.patch('hubtty.app.subprocess.Popen')
    def test_oserror(self, mock_popen, mock_write):
        mock_popen.side_effect = OSError('No such file')

        harness = self._make_harness()
        App._runCustomCommandWorker(harness, '/no/such/cmd', 'Bad cmd',
                                    timeout=30)

        title, message = harness.custom_cmd_queue.get_nowait()
        assert '(error)' in title
        assert 'No such file' in message

    @mock.patch('hubtty.app.os.write')
    @mock.patch('hubtty.app.subprocess.Popen')
    def test_large_output_truncated(self, mock_popen, mock_write):
        proc = mock_popen.return_value
        proc.communicate.return_value = (b'x' * 200000, None)
        proc.returncode = 0

        harness = self._make_harness()
        App._runCustomCommandWorker(harness, 'cat big', 'Big output',
                                    timeout=30)

        title, message = harness.custom_cmd_queue.get_nowait()
        assert '[...truncated...]' in message
        assert len(message) < 70000

    @mock.patch('hubtty.app.os.write')
    @mock.patch('hubtty.app.subprocess.Popen')
    def test_empty_output_success(self, mock_popen, mock_write):
        proc = mock_popen.return_value
        proc.communicate.return_value = (b'', None)
        proc.returncode = 0

        harness = self._make_harness()
        App._runCustomCommandWorker(harness, 'true', 'Silent cmd', timeout=30)

        title, message = harness.custom_cmd_queue.get_nowait()
        assert title == 'Silent cmd'
        assert message == 'Command completed successfully.'
