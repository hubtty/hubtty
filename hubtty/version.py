# Copyright 2014 Hewlett-Packard Development Company, L.P.
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

from importlib.metadata import version, PackageNotFoundError


class VersionInfo:
    """Replacement for pbr.version.VersionInfo that uses importlib.metadata

    Version is dynamically determined from git tags via setuptools-scm during build.
    If the package is not installed (e.g., running from source), falls back to
    trying setuptools_scm directly, or "unknown" as a last resort.
    """

    def __init__(self, package_name):
        self.package_name = package_name
        try:
            self._version = version(package_name)
        except PackageNotFoundError:
            # Try to get version from setuptools_scm if running from git checkout
            try:
                from setuptools_scm import get_version
                self._version = get_version(root='..', relative_to=__file__)
            except Exception:
                self._version = "unknown"

    def release_string(self):
        """Return the version string"""
        return self._version

    def version_string(self):
        """Return the version string (same as release_string for compatibility)"""
        return self._version

    def version_string_with_vcs(self):
        """Return the version string with VCS info if available"""
        return self._version

    def canonical_version_string(self):
        """Return the canonical version string (X.Y.Z without dev/post suffixes)

        This is used for Sphinx documentation to get the short version.
        Strips out post-release and dev suffixes to return just the base version.
        """
        # Extract just the base version (e.g., "0.3.5" from "0.3.5.post16")
        import re
        match = re.match(r'^(\d+\.\d+\.\d+)', self._version)
        if match:
            return match.group(1)
        return self._version


version_info = VersionInfo('hubtty')
