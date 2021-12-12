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


Contents:

.. toctree::
   :maxdepth: 1

   installation.rst
   configuration.rst
   authentication.rst
   usage.rst
   contributing.rst

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

