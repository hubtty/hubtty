Hubtty
======

Hubtty is a console-based interface to the Github Code Review system.

As compared to the web interface, the main advantages are:

 * Workflow -- the interface is designed to support a workflow similar
   to reading network news or mail.  In particular, it is designed to
   deal with a large number of review requests across a large number
   of repositories.

 * Offline Use -- Hubtty syncs information about pull requests in subscribed
   repositories to a local database and local git repos.  All review
   operations are performed against that database and then synced back
   to Github.

 * Speed -- user actions modify locally cached content and need not
   wait for server interaction.

 * Convenience -- because Hubtty downloads all pull requests to local git
   repos, a single command instructs it to checkout a pull request into that
   repo for detailed examination or testing of larger pull requests.

Installation
------------

Source
~~~~~~

When installing from source, it is recommended (but not required) to
install Hubtty in a virtualenv.  To set one up::

  virtualenv hubtty-env
  source hubtty-env/bin/activate

To install the latest version from the cheeseshop::

  pip install hubtty

To install from a git checkout::

  pip install .

Hubtty uses a YAML based configuration file that it looks for at
``$XDG_CONFIG_HOME/hubtty/hubtty.yaml``.  Several sample configuration files
are included.  You can find them in the examples/ directory of the
`source distribution
<https://github.com/hubtty/hubtty/tree/master/examples>`_ or
the share/hubtty/examples directory after installation.

The sample config files are as follows:

**minimal-hubtty.yaml**
  Only contains the parameters required for Hubtty to actually run.

**reference-hubtty.yaml**
  An exhaustive list of all supported options with examples.

**openshift-hubtty.yaml**
  A configuration designed for OpenShift reviews.

Hubtty uses local git repositories to perform much of its work.  These
can be the same git repositories that you use when developing a
project.  Hubtty will not alter the working directory or index unless
you request it to (and even then, the usual git safeguards against
accidentally losing work remain in place).  You will need to supply
the name of a directory where Hubtty will find or clone git
repositories for your projects as the ``git-root`` parameter.

The config file is designed to support multiple Github instances.  The
first one is used by default, but others can be specified by supplying
the name on the command line.

Usage
-----

After installing Hubtty, you should be able to run it by invoking
``hubtty``.  If you installed it in a virtualenv, you can invoke it
without activating the virtualenv with ``/path/to/venv/bin/hubtty``
which you may wish to add to your shell aliases.  Use ``hubtty
--help`` to see a list of command line options available.

Once Hubtty is running, you will need to start by subscribing to some
repositories.  Use 'L' to list all of the repositories and then 's' to
subscribe to the ones you are interested in.  Hit 'L' again to shrink
the list to your subscribed repositories.

In general, pressing the F1 key will show help text on any screen, and
ESC will take you to the previous screen.

Hubtty works seamlessly offline or online.  All of the actions that it
performs are first recorded in a local database (in ``$XDG_DATA_HOME/hubtty/hubtty.db``
by default), and are then transmitted to Github.  If Hubtty is unable
to contact Github for any reason, it will continue to operate against
the local database, and once it re-establishes contact, it will
process any pending changes.

The status bar at the top of the screen displays the current number of
outstanding tasks that Hubtty must perform in order to be fully up to
date.  Some of these tasks are more complicated than others, and some
of them will end up creating new tasks (for instance, one task may be
to search for new pull requests in a repository which will then produce
5 new tasks if there are 5 new pull requests).

If Hubtty is offline, it will so indicate in the status bar.  It will
retry requests if needed, and will switch between offline and online
mode automatically.

If you review a pull request while offline with a positive vote, and someone
else leaves a negative vote on that pull request before Hubtty is able to
upload your review, Hubtty will detect the situation and mark the pull request
as "held" so that you may re-inspect the pull request and any new comments
before uploading the review.  The status bar will alert you to any held pull
requests and direct you to a list of them (the `F12` key by default).  When
viewing a pull request, the "held" flag may be toggled with the exclamation key
(`!`).  Once held, a pull request must be explicitly un-held in this manner for
your review to be uploaded.

If Hubtty encounters an error, this will also be indicated in the status bar.
You may wish to examine ``$XDG_DATA_HOME/hubtty/hubtty.log`` to see what the
error was.  In many cases, Hubtty can continue after encountering an error.
The error flag will be cleared when you leave the current screen.

To select text (e.g., to copy to the clipboard), hold Shift while
selecting the text.

MacOS
~~~~~

The MacOS terminal blocks ctrl+o, which is the default search key combo in
Hubtty. To fix this, a custom keymap can be used on MacOS which modifies the
search key combo. For example::

  keymaps:
    - name: default # MacOS blocks ctrl+o
      pr-search: 'ctrl s'
      interactive-search: 'ctrl i'

Contributing
------------

For information on how to contribute to Hubtty, please see the
contents of the CONTRIBUTING.rst file.

Bugs
----

Bugs are handled at: https://github.com/hubtty/hubtty/issues
