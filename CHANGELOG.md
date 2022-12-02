# Hubtty changelog

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
