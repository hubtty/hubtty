# Copyright 2025 The hubtty developers
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

"""Tests for DiffFile.expand_tabs with syntax markup."""

from hubtty.gitrepo import DiffFile


class TestExpandTabsPlainString:

    def test_no_tabs(self):
        f = DiffFile()
        assert f.expand_tabs('hello') == 'hello'

    def test_single_tab_at_start(self):
        f = DiffFile()
        result = f.expand_tabs('\thello')
        # Tab at column 0 with tabstop=8 → '»' + 7 spaces
        assert result == '»' + ' ' * 7 + 'hello'

    def test_tab_after_text(self):
        f = DiffFile()
        result = f.expand_tabs('ab\tcd')
        # 'ab' occupies columns 0-1, tab at column 2 → 6 fill chars
        assert result == 'ab»' + ' ' * 5 + 'cd'

    def test_multiple_tabs(self):
        f = DiffFile()
        result = f.expand_tabs('\t\t')
        # First tab: col 0 → '»' + 7 spaces (cols 0-7)
        # Second tab: col 8 → '»' + 7 spaces (cols 8-15)
        assert result == '»' + ' ' * 7 + '»' + ' ' * 7


class TestExpandTabsSyntaxTuples:

    def test_tuple_with_tab(self):
        f = DiffFile()
        result = f.expand_tabs(('syn-keyword', '\tdef'))
        assert result == ('syn-keyword', '»' + ' ' * 7 + 'def')

    def test_tuple_no_tab(self):
        f = DiffFile()
        result = f.expand_tabs(('syn-keyword', 'def'))
        assert result == ('syn-keyword', 'def')


class TestExpandTabsList:

    def test_list_of_strings(self):
        f = DiffFile()
        result = f.expand_tabs(['hello', '\tworld'])
        assert result == ['hello', '»' + ' ' * 2 + 'world']

    def test_list_of_tuples(self):
        f = DiffFile()
        result = f.expand_tabs([('syn-keyword', 'def'), ('syn-name-function', '\tfoo')])
        # 'def' occupies columns 0-2 (3 chars), tab at column 3 → 5 fill
        assert result == [
            ('syn-keyword', 'def'),
            ('syn-name-function', '»' + ' ' * 4 + 'foo'),
        ]

    def test_list_mixed_strings_and_tuples(self):
        f = DiffFile()
        result = f.expand_tabs(['ab', ('syn-keyword', '\tif')])
        # 'ab' occupies columns 0-1, tab at column 2 → 6 fill chars
        assert result == ['ab', ('syn-keyword', '»' + ' ' * 5 + 'if')]

    def test_tab_spans_across_segments(self):
        """Tab position should account for characters in prior segments."""
        f = DiffFile()
        # 4 chars in first segment, then tab in second
        result = f.expand_tabs([('syn-type', 'int '), ('syn-name-function', '\tfoo')])
        # 'int ' = 4 cols, tab at col 4 → 4 fill chars
        assert result == [
            ('syn-type', 'int '),
            ('syn-name-function', '»' + ' ' * 3 + 'foo'),
        ]

    def test_tab_at_exact_tabstop_boundary(self):
        """Tab at an exact tabstop boundary should expand to a full tabstop."""
        f = DiffFile()
        # 8 chars in first segment puts us exactly at col 8
        result = f.expand_tabs(['12345678', '\tx'])
        # Tab at col 8 → next stop is 16, so '»' + 7 spaces
        assert result == ['12345678', '»' + ' ' * 7 + 'x']

    def test_multiple_tabs_across_segments(self):
        f = DiffFile()
        result = f.expand_tabs([('a', '\t'), ('b', '\t')])
        # First tab at col 0 → '»'+7sp (fills to col 8)
        # Second tab at col 8 → '»'+7sp (fills to col 16)
        assert result == [
            ('a', '»' + ' ' * 7),
            ('b', '»' + ' ' * 7),
        ]

    def test_custom_tabstop(self):
        f = DiffFile()
        result = f.expand_tabs(['ab', ('syn-keyword', '\tx')], tabstop=4)
        # 'ab' = 2 cols, tab at col 2 with tabstop=4 → 2 fill chars
        assert result == ['ab', ('syn-keyword', '»' + ' ' + 'x')]

    def test_empty_list(self):
        f = DiffFile()
        assert f.expand_tabs([]) == []

    def test_empty_string(self):
        f = DiffFile()
        assert f.expand_tabs('') == ''
