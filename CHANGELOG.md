# Hubtty changelog

## Release 0.4 - 2026/06/21

### Breaking changes

- Require Python 3.10 as minimum version ([#103](https://github.com/hubtty/hubtty/pull/103))
- Switch from tox to uv for development and publishing ([#104](https://github.com/hubtty/hubtty/pull/104))
- Remove built-in local checkout and local cherry-pick commands ([#137](https://github.com/hubtty/hubtty/pull/137))

### New features

- Add custom-commands: bind keys to run shell commands, with show-output option and {repo_path} variable ([#124](https://github.com/hubtty/hubtty/pull/124)) and ([#137](https://github.com/hubtty/hubtty/pull/137))
- Add syntax highlighting to diff views ([#117](https://github.com/hubtty/hubtty/pull/117))
- Add key binding to toggle between unified and side-by-side diff ([#121](https://github.com/hubtty/hubtty/pull/121))
- Add sync task queue viewer (Ctrl+T) with clickable Sync status in header bar ([#115](https://github.com/hubtty/hubtty/pull/115))
- Add ETag / conditional request support to HTTP client ([#111](https://github.com/hubtty/hubtty/pull/111))
- Add lightweight CI check polling with SyncPullRequestChecksTask ([#112](https://github.com/hubtty/hubtty/pull/112))
- Add ignore-pending-checks config to skip perpetually-pending check contexts ([#112](https://github.com/hubtty/hubtty/pull/112))
- Auto-link GitHub issue/PR references (#N) in comments ([#123](https://github.com/hubtty/hubtty/pull/123))

### Bug fixes

- Fix possible crash on rebased PRs ([#102](https://github.com/hubtty/hubtty/pull/102))
- Handle inline_html in markdown renderer ([#110](https://github.com/hubtty/hubtty/pull/110))
- Make rate limit handling more robust ([#107](https://github.com/hubtty/hubtty/pull/107))
- Fix check-runs pagination losing all but last page ([#118](https://github.com/hubtty/hubtty/pull/118))
- Handle skipped and cancelled check run conclusions ([#116](https://github.com/hubtty/hubtty/pull/116))
- Fix MultiQueue dedup to check all priorities and incomplete list ([#113](https://github.com/hubtty/hubtty/pull/113))
- Fix check retry tasks being silently rejected by queue deduplication ([#122](https://github.com/hubtty/hubtty/pull/122))
- Skip per-commit detail fetches for commits already in local DB ([#114](https://github.com/hubtty/hubtty/pull/114))
- Catch SearchSyntaxError in dashboard and repository views ([#120](https://github.com/hubtty/hubtty/pull/120))
- Fix SQLAlchemy 2.0 compatibility: select() calls, scalar subquery warnings, .copy() deprecation ([#126](https://github.com/hubtty/hubtty/pull/126))
- Fix duplicate checks caused by overlapping GitHub APIs ([#129](https://github.com/hubtty/hubtty/pull/129))
- Skip empty COMMENT/REQUEST_CHANGES reviews to avoid 422 ([#128](https://github.com/hubtty/hubtty/pull/128))
- Fix NOT NULL crash for parentless commits during PR sync ([#132](https://github.com/hubtty/hubtty/pull/132))
- Fix fetch failing when target branch is checked out ([#133](https://github.com/hubtty/hubtty/pull/133))
- Fix typo in markdown parser: linebeak to linebreak ([#134](https://github.com/hubtty/hubtty/pull/134))
- Handle invalid configuration file gracefully ([#138](https://github.com/hubtty/hubtty/pull/138))
- Treat all 5xx errors as transient (offline) instead of failing the task ([#140](https://github.com/hubtty/hubtty/pull/140))
- Schedule check re-poll when no checks reported yet ([#139](https://github.com/hubtty/hubtty/pull/139))
- Detect search API truncation and fall back to per-repo queries ([#142](https://github.com/hubtty/hubtty/pull/142))

### Internal

- Python 3.10 modernization: pyupgrade, f-strings, match/case, drop six/future/ordereddict ([#103](https://github.com/hubtty/hubtty/pull/103))
- Break up sync module into separate files ([#106](https://github.com/hubtty/hubtty/pull/106))
- Remove pin on older mistune library ([#105](https://github.com/hubtty/hubtty/pull/105))
- Replace custom SQLite migration helpers with Alembic batch_alter_table ([#130](https://github.com/hubtty/hubtty/pull/130))
- Add unit test CI job ([#108](https://github.com/hubtty/hubtty/pull/108))
- Update dependencies ([#109](https://github.com/hubtty/hubtty/pull/109))
- Add security warning for custom commands in example config ([#141](https://github.com/hubtty/hubtty/pull/141))

## Release 0.3.5 - 2024/11/09

- Fix compatibility with SQLAlchemy v2 ([#100](https://github.com/hubtty/hubtty/pull/100))

## Release 0.3.4 - 2024/10/13

- Fix db.vacuum ([#99](https://github.com/hubtty/hubtty/pull/99))

## Release 0.3.3 - 2024/10/13

- Fix urwid > 2.4.2 compatibility ([#98](https://github.com/hubtty/hubtty/pull/98))
- Bump sqlalchemy dependency ([#97](https://github.com/hubtty/hubtty/pull/97))

## Release 0.3.2 - 2024/01/03

- Pin mistune to v2 ([#96](https://github.com/hubtty/hubtty/pull/96))
- Require urwid 2.2.0 as minimum version ([#96](https://github.com/hubtty/hubtty/pull/96))

## Release 0.3.1 - 2023/09/19

- Skip approval when review is not tied to a commit ([#95](https://github.com/hubtty/hubtty/pull/95))

## Release 0.3 - 2022/12/02

- Show colored labels for terminals that support it ([#85](https://github.com/hubtty/hubtty/pull/85))
- Add example commentlink for openshift's Jira ([#84](https://github.com/hubtty/hubtty/pull/84))
- Fix sync failure for parent-less commits ([#88](https://github.com/hubtty/hubtty/pull/88)) and ([#89](https://github.com/hubtty/hubtty/pull/89))
- Fix possible sync failure for force-pushed PR ([#91](https://github.com/hubtty/hubtty/pull/91))
- Use Github's versioned REST API ([#92](https://github.com/hubtty/hubtty/pull/92))

## Release 0.2 - 2022/08/20

- Highlight and search for draft PRs ([#79](https://github.com/hubtty/hubtty/pull/79))
- Render markdown ([#81](https://github.com/hubtty/hubtty/pull/81)) and ([#82](https://github.com/hubtty/hubtty/pull/82))

## Release 0.1.2 - 2021/12/12

- Fix example config file search path when installing with `pip install --user` ([#76](https://github.com/hubtty/hubtty/pull/76))
- Document limitation with OAuth apps ([#77](https://github.com/hubtty/hubtty/pull/77))
- Minor documentation fixes ([#78](https://github.com/hubtty/hubtty/pull/78))

## Release 0.1.1 - 2021/11/08

- Fix issue with alembic >= 1.7 ([#73](https://github.com/hubtty/hubtty/pull/73))

## Release 0.1 - Mostly Works - 2021/10/08

Very first release of Hubtty:

- Forks [Gertty](https://opendev.org/ttygroup/gertty.git) at commit [f49f27db59](https://opendev.org/ttygroup/gertty/src/commit/f49f27db596816b2a291e4b3b41d353ee5c63fbd)
- Implements the Github device flow to generate an OAuth token on the user's behalf
- Stores the authentication token in a separate configuration file, allowing to save the main configuration file under a public git repository
- Creates a default configuration file on first use
- Follows XDG recommendations
- Populates the initial list of repositories with the ones the user has write access to
- PR oriented instead of commit oriented
- Partially implements Github search syntax ([#48](https://github.com/hubtty/hubtty/issues/48))
- Supports Github API rate-limiting
- Follows Github terminology
