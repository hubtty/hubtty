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

"""Tests for the generated-file detection module."""

import textwrap

from hubtty.generated import (
    BUILTIN_GENERATED_PATTERNS,
    GeneratedFileFilter,
    _glob_to_regex,
    _match_pattern,
    parse_gitattributes,
    read_gitattributes,
)


# ---------------------------------------------------------------------------
# _match_pattern
# ---------------------------------------------------------------------------

class TestMatchPattern:
    """Low-level pattern matching."""

    # --- basename-only patterns (no slash) ---

    def test_basename_star_extension(self):
        assert _match_pattern('*.min.js', 'app.min.js')
        assert _match_pattern('*.min.js', 'src/app.min.js')
        assert not _match_pattern('*.min.js', 'app.js')

    def test_basename_exact(self):
        assert _match_pattern('package-lock.json', 'package-lock.json')
        assert _match_pattern('package-lock.json', 'frontend/package-lock.json')
        assert not _match_pattern('package-lock.json', 'package.json')

    def test_basename_prefix_star(self):
        assert _match_pattern('*_pb2.py', 'message_pb2.py')
        assert _match_pattern('*_pb2.py', 'proto/message_pb2.py')
        assert not _match_pattern('*_pb2.py', 'message.py')

    # --- patterns with slash ---

    def test_directory_doublestar(self):
        assert _match_pattern('vendor/**', 'vendor/lib.go')
        assert _match_pattern('vendor/**', 'vendor/sub/lib.go')
        assert not _match_pattern('vendor/**', 'src/vendor.go')

    def test_directory_single_star(self):
        """Single * should NOT cross directory boundaries."""
        assert _match_pattern('vendor/*', 'vendor/lib.go')
        assert not _match_pattern('vendor/*', 'vendor/sub/lib.go')

    def test_doublestar_prefix(self):
        """**/name matches name in any directory."""
        assert _match_pattern('**/foo.txt', 'foo.txt')
        assert _match_pattern('**/foo.txt', 'a/foo.txt')
        assert _match_pattern('**/foo.txt', 'a/b/foo.txt')
        assert not _match_pattern('**/foo.txt', 'foo.txtx')

    def test_mid_doublestar(self):
        """a/**/b matches a/b and a/x/b and a/x/y/b."""
        assert _match_pattern('a/**/b', 'a/b')
        assert _match_pattern('a/**/b', 'a/x/b')
        assert _match_pattern('a/**/b', 'a/x/y/b')
        assert not _match_pattern('a/**/b', 'z/a/b')

    def test_trailing_slash_stripped(self):
        """Trailing / is stripped (directory marker)."""
        assert _match_pattern('vendor/', 'vendor')

    def test_empty_pattern(self):
        assert not _match_pattern('', 'anything')
        assert not _match_pattern('  ', 'anything')

    def test_unclosed_bracket_does_not_raise(self):
        """An unclosed '[' produces an invalid regex; _match_pattern
        should return False instead of raising re.error."""
        assert not _match_pattern('src/[bad', 'src/bad')
        assert not _match_pattern('src/[', 'src/x')


# ---------------------------------------------------------------------------
# _glob_to_regex
# ---------------------------------------------------------------------------

class TestGlobToRegex:
    def test_doublestar_slash(self):
        regex = _glob_to_regex('**/')
        assert regex == '(?:.+/)?'

    def test_doublestar_end(self):
        regex = _glob_to_regex('**')
        assert regex == '.*'

    def test_single_star(self):
        regex = _glob_to_regex('*')
        assert regex == '[^/]*'

    def test_question_mark(self):
        regex = _glob_to_regex('?')
        assert regex == '[^/]'

    def test_literal(self):
        regex = _glob_to_regex('foo.txt')
        assert regex == r'foo\.txt'


# ---------------------------------------------------------------------------
# parse_gitattributes
# ---------------------------------------------------------------------------

class TestParseGitattributes:
    def test_generated_true(self):
        content = '*.pb.go linguist-generated=true\n'
        gen, not_gen = parse_gitattributes(content)
        assert gen == ['*.pb.go']
        assert not_gen == []

    def test_generated_bare(self):
        content = '*.pb.go linguist-generated\n'
        gen, not_gen = parse_gitattributes(content)
        assert gen == ['*.pb.go']

    def test_generated_false(self):
        content = '*.pb.go linguist-generated=false\n'
        gen, not_gen = parse_gitattributes(content)
        assert gen == []
        assert not_gen == ['*.pb.go']

    def test_unset_minus(self):
        content = '*.pb.go -linguist-generated\n'
        gen, not_gen = parse_gitattributes(content)
        assert gen == []
        assert not_gen == ['*.pb.go']

    def test_multiple_attrs(self):
        content = '*.pb.go diff merge linguist-generated=true\n'
        gen, not_gen = parse_gitattributes(content)
        assert gen == ['*.pb.go']

    def test_comments_and_blanks(self):
        content = textwrap.dedent("""\
            # comment
            *.pb.go linguist-generated

            *.min.js linguist-generated=true
        """)
        gen, not_gen = parse_gitattributes(content)
        assert gen == ['*.pb.go', '*.min.js']

    def test_mixed(self):
        content = textwrap.dedent("""\
            vendor/** linguist-generated=true
            vendor/important.go linguist-generated=false
        """)
        gen, not_gen = parse_gitattributes(content)
        assert gen == ['vendor/**']
        assert not_gen == ['vendor/important.go']

    def test_empty(self):
        gen, not_gen = parse_gitattributes('')
        assert gen == []
        assert not_gen == []

    def test_no_attrs(self):
        gen, not_gen = parse_gitattributes('*.go\n')
        assert gen == []
        assert not_gen == []


# ---------------------------------------------------------------------------
# read_gitattributes
# ---------------------------------------------------------------------------

class TestReadGitattributes:
    def test_read_from_disk(self, tmp_path):
        attr = tmp_path / '.gitattributes'
        attr.write_text('*.pb.go linguist-generated\n')
        content = read_gitattributes(str(tmp_path))
        assert '*.pb.go' in content

    def test_missing_file(self, tmp_path):
        content = read_gitattributes(str(tmp_path))
        assert content == ''


# ---------------------------------------------------------------------------
# GeneratedFileFilter
# ---------------------------------------------------------------------------

class TestGeneratedFileFilter:
    """Integration tests for the filter combining all pattern sources."""

    def test_builtin_lock_files(self):
        filt = GeneratedFileFilter()
        assert filt.is_generated('package-lock.json')
        assert filt.is_generated('yarn.lock')
        assert filt.is_generated('Cargo.lock')
        assert filt.is_generated('go.sum')
        assert filt.is_generated('Pipfile.lock')
        assert filt.is_generated('poetry.lock')
        assert filt.is_generated('Gemfile.lock')
        assert filt.is_generated('composer.lock')

    def test_builtin_lock_files_in_subdirectory(self):
        filt = GeneratedFileFilter()
        assert filt.is_generated('frontend/package-lock.json')
        assert filt.is_generated('services/api/yarn.lock')

    def test_builtin_minified(self):
        filt = GeneratedFileFilter()
        assert filt.is_generated('app.min.js')
        assert filt.is_generated('dist/style.min.css')
        assert not filt.is_generated('app.js')
        assert not filt.is_generated('style.css')

    def test_builtin_protobuf(self):
        filt = GeneratedFileFilter()
        assert filt.is_generated('proto/msg.pb.go')
        assert filt.is_generated('api/service_pb2.py')
        assert filt.is_generated('api/service_pb2_grpc.py')

    def test_builtin_csharp(self):
        filt = GeneratedFileFilter()
        assert filt.is_generated('Form1.Designer.cs')
        assert filt.is_generated('Form1.designer.cs')
        assert filt.is_generated('Model.g.cs')
        assert filt.is_generated('Dto.generated.cs')

    def test_builtin_vendor_directories(self):
        filt = GeneratedFileFilter()
        assert filt.is_generated('vendor/lib.go')
        assert filt.is_generated('vendor/github.com/foo/bar/baz.go')
        assert filt.is_generated('node_modules/lodash/index.js')
        assert filt.is_generated('node_modules/@scope/pkg/lib.js')
        assert filt.is_generated('third_party/protobuf/message.cc')
        assert filt.is_generated('third_party/deep/nested/file.h')
        # Files that merely *contain* the word vendor are not matched.
        assert not filt.is_generated('src/vendor.go')
        assert not filt.is_generated('my_vendor_lib.py')

    def test_normal_files_not_generated(self):
        filt = GeneratedFileFilter()
        assert not filt.is_generated('main.py')
        assert not filt.is_generated('src/app.tsx')
        assert not filt.is_generated('README.md')
        assert not filt.is_generated('Makefile')
        assert not filt.is_generated('go.mod')
        assert not filt.is_generated('Cargo.toml')

    def test_user_patterns(self):
        filt = GeneratedFileFilter(user_patterns=['*.snap', 'generated/**'])
        assert filt.is_generated('Button.test.snap')
        assert filt.is_generated('generated/schema.graphql')
        assert not filt.is_generated('src/Button.tsx')

    def test_gitattributes_from_disk(self, tmp_path):
        attr = tmp_path / '.gitattributes'
        attr.write_text('docs/api.json linguist-generated=true\n')
        filt = GeneratedFileFilter(repo_path=str(tmp_path))
        assert filt.is_generated('docs/api.json')

    def test_gitattributes_not_generated_overrides_builtin(self, tmp_path):
        """linguist-generated=false in .gitattributes overrides builtins."""
        attr = tmp_path / '.gitattributes'
        attr.write_text('package-lock.json linguist-generated=false\n')
        filt = GeneratedFileFilter(repo_path=str(tmp_path))
        assert not filt.is_generated('package-lock.json')

    def test_gitattributes_not_generated_overrides_user(self, tmp_path):
        """linguist-generated=false overrides user-supplied patterns."""
        attr = tmp_path / '.gitattributes'
        attr.write_text('*.snap linguist-generated=false\n')
        filt = GeneratedFileFilter(
            repo_path=str(tmp_path), user_patterns=['*.snap'])
        assert not filt.is_generated('Button.test.snap')

    def test_no_repo_path(self):
        """Filter works without a repo path (builtins only)."""
        filt = GeneratedFileFilter()
        assert filt.is_generated('yarn.lock')
        assert not filt.is_generated('README.md')

    def test_commit_msg_not_generated(self):
        filt = GeneratedFileFilter()
        assert not filt.is_generated('/COMMIT_MSG')

    def test_all_builtin_patterns_are_strings(self):
        for p in BUILTIN_GENERATED_PATTERNS:
            assert isinstance(p, str)
