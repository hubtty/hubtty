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

"""Detect generated files using .gitattributes, built-in heuristics, and
user-configured patterns.

Four sources of patterns are combined (checked in this order):

1. ``.gitattributes`` ``linguist-generated=false`` markers — these
   explicitly *exclude* a path from being considered generated and
   take highest precedence.
2. ``.gitattributes`` ``linguist-generated`` / ``linguist-generated=true``
   markers.
3. Built-in heuristic patterns for commonly generated files (lock
   files, protobuf output, minified assets, etc.) derived from
   GitHub Linguist.
4. User-supplied glob patterns from the Hubtty configuration file
   (``generated-files`` list).
"""

import fnmatch
import logging
import os
import re

import git
import gitdb

log = logging.getLogger(__name__)

# Built-in patterns for commonly generated files, derived from GitHub
# Linguist's generated.rb heuristics:
# https://github.com/github-linguist/linguist/blob/master/lib/linguist/generated.rb
#
# Only filename-based patterns are included; content-based detection
# (e.g. ``@generated`` markers) is not performed.
#
# The list intentionally favours precision over recall — it is better
# to miss a generated file than to wrongly hide a hand-written one.
# Users can extend this via the ``generated-files`` config option or
# via ``linguist-generated`` markers in ``.gitattributes``.
BUILTIN_GENERATED_PATTERNS = [
    # Lock files / dependency checksums
    'package-lock.json',
    'yarn.lock',
    'pnpm-lock.yaml',
    'Cargo.lock',
    'go.sum',
    'Pipfile.lock',
    'poetry.lock',
    'Gemfile.lock',
    'composer.lock',
    'flake.lock',
    'packages.lock.json',
    # Minified files
    '*.min.js',
    '*.min.css',
    '*.min.js.map',
    '*.min.css.map',
    # Protobuf generated
    '*.pb.go',
    '*.pb.h',
    '*.pb.cc',
    '*_pb2.py',
    '*_pb2_grpc.py',
    '*.pb.swift',
    '*.pb.rb',
    # .NET / C# generated
    '*.designer.cs',
    '*.Designer.cs',
    '*.g.cs',
    '*.generated.cs',
    # Vendored dependencies
    'vendor/**',
    'node_modules/**',
    'third_party/**',
]


def _glob_to_regex(pattern):
    """Convert a gitattributes-style glob *pattern* to a regex string.

    Within a pattern that contains ``/``:

    * ``**`` matches zero or more path components (including ``/``).
    * ``*``  matches within a single path component (no ``/``).
    * ``?``  matches a single non-``/`` character.

    The returned string is *not* anchored — callers should wrap it
    with ``^…$`` as needed.
    """
    i = 0
    n = len(pattern)
    parts = []
    while i < n:
        c = pattern[i]
        if c == '*':
            if i + 1 < n and pattern[i + 1] == '*':
                # "**" — match everything including "/"
                i += 2
                # Consume a trailing "/" so that "**/foo" works as
                # "any prefix (possibly empty) ending in /".
                if i < n and pattern[i] == '/':
                    parts.append('(?:.+/)?')
                    i += 1
                else:
                    parts.append('.*')
                continue
            else:
                # Single "*" — match within one path component
                parts.append('[^/]*')
        elif c == '?':
            parts.append('[^/]')
        elif c == '[':
            # Pass character classes through verbatim.
            j = i + 1
            if j < n and pattern[j] == '!':
                j += 1
            if j < n and pattern[j] == ']':
                j += 1
            while j < n and pattern[j] != ']':
                j += 1
            parts.append(pattern[i:j + 1])
            i = j
        else:
            parts.append(re.escape(c))
        i += 1
    return ''.join(parts)


def _match_pattern(pattern, path):
    """Match a gitattributes-style glob *pattern* against a file *path*.

    Matching rules (following gitattributes/gitignore conventions):

    * If *pattern* contains no ``/`` it is matched against the
      **basename** of *path* using :func:`fnmatch.fnmatch`.
    * Otherwise it is matched against the full *path* using a regex
      derived from the pattern where ``*`` does not cross directory
      boundaries and ``**`` does.

    A trailing ``/`` on *pattern* is stripped before matching (it
    denotes "directory only" in gitignore, but we match files).

    Args:
        pattern: A glob pattern (e.g. ``*.min.js``, ``vendor/**``).
        path: A repository-relative file path (forward-slash separated).

    Returns:
        ``True`` if *path* matches *pattern*.
    """
    pattern = pattern.strip()
    if pattern.endswith('/'):
        pattern = pattern[:-1]
    if not pattern:
        return False

    if '/' not in pattern:
        # No directory component — match against the basename only.
        return fnmatch.fnmatch(os.path.basename(path), pattern)

    # Pattern contains a "/" — match against the full path with
    # proper * vs ** semantics.
    regex = '^' + _glob_to_regex(pattern) + '$'
    try:
        return bool(re.match(regex, path))
    except re.error:
        log.debug("Invalid glob pattern %r (bad regex %r)",
                  pattern, regex)
        return False


def parse_gitattributes(content):
    """Parse ``.gitattributes`` content for ``linguist-generated`` markers.

    Args:
        content: The text content of a ``.gitattributes`` file.

    Returns:
        A tuple ``(generated, not_generated)`` where each element is a
        list of glob pattern strings.  *generated* lists patterns
        explicitly marked as generated; *not_generated* lists patterns
        explicitly marked as **not** generated
        (``linguist-generated=false`` or ``-linguist-generated``).
    """
    generated = []
    not_generated = []

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        parts = line.split()
        if len(parts) < 2:
            continue

        pattern = parts[0]
        for attr in parts[1:]:
            if attr in ('linguist-generated', 'linguist-generated=true'):
                generated.append(pattern)
            elif attr in ('-linguist-generated', 'linguist-generated=false'):
                not_generated.append(pattern)

    return generated, not_generated


def read_gitattributes(repo_path, commit_sha=None):
    """Read ``.gitattributes`` content from a git repository.

    Args:
        repo_path: Path to the local git clone.
        commit_sha: Optional commit SHA to read from.  When given the
            file is read from that commit's tree; otherwise the
            working-tree copy on disk is used.

    Returns:
        The file content as a string, or ``''`` if the file does not
        exist or cannot be read.
    """
    if commit_sha:
        try:
            repo = git.Repo(repo_path)
            commit = repo.commit(commit_sha)
            blob = commit.tree['.gitattributes']
            return blob.data_stream.read().decode('utf-8', errors='replace')
        except (KeyError, gitdb.exc.BadObject, ValueError):
            return ''
        except Exception:
            log.debug("Failed to read .gitattributes from commit %s",
                      commit_sha, exc_info=True)
            return ''

    attr_path = os.path.join(repo_path, '.gitattributes')
    try:
        with open(attr_path) as f:
            return f.read()
    except OSError:
        return ''


class GeneratedFileFilter:
    """Determine whether repository files are generated.

    Combines three pattern sources (see module docstring for details).
    A ``.gitattributes`` ``linguist-generated=false`` entry takes
    highest precedence and can un-mark a file that would otherwise
    match a built-in or user-supplied pattern.

    Usage::

        filt = GeneratedFileFilter(
            repo_path='/path/to/clone',
            commit_sha='abc123',
            user_patterns=['*.snap'],
        )
        filt.is_generated('package-lock.json')   # True
        filt.is_generated('src/app.py')           # False

    Args:
        repo_path: Path to the local git clone (optional).  When
            provided the ``.gitattributes`` file is read from this
            repository.
        commit_sha: Commit SHA to read ``.gitattributes`` from
            (optional; falls back to the working-tree copy).
        user_patterns: Extra glob patterns supplied via the Hubtty
            ``generated-files`` configuration option.
    """

    def __init__(self, repo_path=None, commit_sha=None, user_patterns=None):
        self._generated_patterns = list(BUILTIN_GENERATED_PATTERNS)
        self._not_generated_patterns = []

        if user_patterns:
            self._generated_patterns.extend(user_patterns)

        if repo_path:
            content = read_gitattributes(repo_path, commit_sha)
            if content:
                ga_gen, ga_not = parse_gitattributes(content)
                self._generated_patterns.extend(ga_gen)
                self._not_generated_patterns.extend(ga_not)

    def is_generated(self, path):
        """Return ``True`` if *path* should be considered a generated file.

        Args:
            path: Repository-relative file path (e.g.
                ``src/proto/foo.pb.go``).
        """
        # Explicit "not generated" markers always win.
        for pattern in self._not_generated_patterns:
            if _match_pattern(pattern, path):
                return False

        for pattern in self._generated_patterns:
            if _match_pattern(pattern, path):
                return True

        return False
