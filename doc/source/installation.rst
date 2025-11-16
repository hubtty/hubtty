Installation
------------

Source
~~~~~~

**With uv (recommended)**

The modern way to install and develop Hubtty is with `uv <https://github.com/astral-sh/uv>`_::

  # Install from PyPI
  uv tool install hubtty

  # Or install from a git checkout for development
  git clone https://github.com/hubtty/hubtty
  cd hubtty
  uv sync
  uv run hubtty

This automatically manages the virtual environment and dependencies for you.

**With pip (traditional)**

When installing from source, it is recommended (but not required) to
install Hubtty in a virtualenv.  To set one up::

  virtualenv hubtty-env
  source hubtty-env/bin/activate

To install the latest version from the cheeseshop::

  pip install hubtty

To install from a git checkout::

  pip install .
