# Hubtty changelog

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
