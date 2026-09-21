# SPDX-FileCopyrightText: 2026 CERN
# SPDX-License-Identifier: GPL-3.0-or-later

"""Upload a file that lives INSIDE a built package next to the release's BOMs.

Some packages generate a file that consumers need *before* they download
anything — the install Makefile a package writes to its own $INSTALLROOT is the
motivating case: fetching the package to read the list of what to fetch is
circular. Publishing that file alongside the manifests breaks the cycle, using
the same MANIFESTS/<build_id>/ prefix as NOTICE and LICENSE-SOURCE-OFFER.txt:

    MANIFESTS/<build_id>/<effective_architecture>/<package>/<basename>

The file is read from the local install tree (<work_dir>/<arch>/<family>/
<package>/<version>-<revision>/<relpath>), which is where the build left it, so
nothing is unpacked and no S3 object is fetched. Keys have no ``.json``
extension, so `bits compliance` (which parses every .json under MANIFESTS/ as a
BOM) and `bits certify` ignore them.

Best-effort, exactly like upload_release_compliance: a failure here never fails
a publish.
"""

import os

from bits_helpers.log import debug, info, warning


def package_dir(entry, work_dir="sw"):
  """Local install directory of a manifest *entry*, or None if unusable.

  Mirrors the layout build_template.sh installs into:
  ``<work_dir>/<effective_architecture>/<pkg_family>/<package>/<version>-<revision>``,
  with the family segment omitted when the entry has none (defaults-*) and the
  ``-<revision>`` suffix omitted when the revision is empty (force_revision: "").
  """
  package = entry.get("package")
  arch = entry.get("effective_architecture")
  version = entry.get("version")
  if not (package and arch and version):
    return None
  revision = str(entry.get("revision") or "")
  ver_rev = "%s-%s" % (version, revision) if revision else version
  family = entry.get("pkg_family") or ""
  return os.path.join(work_dir, arch, family, package, ver_rev)


def upload_release_package_file(s3, bucket, build_id, entries, relpath,
                                work_dir="sw", packages=None, content_type=None):
  """Upload ``<relpath>`` from inside each built package next to the BOMs.

  *entries* are manifest entries (as passed to upload_release_compliance);
  *relpath* is the path of the file within the package, e.g. ``"Makefile"`` or
  ``"etc/deps/provides.json"``. Packages that do not carry the file are skipped
  silently — most of them won't. Pass *packages* to restrict the upload to
  those package names.

  Returns the number of files uploaded. Never raises.
  """
  wanted = set(packages) if packages else None
  uploaded = 0
  for entry in entries or []:
    name = entry.get("package")
    if wanted is not None and name not in wanted:
      continue
    pkg_dir = package_dir(entry, work_dir)
    if pkg_dir is None:
      continue
    path = os.path.join(pkg_dir, relpath)
    if not os.path.isfile(path):
      continue
    key = "MANIFESTS/%s/%s/%s/%s" % (build_id, entry["effective_architecture"],
                                     name, os.path.basename(relpath))
    try:
      with open(path, "rb") as fh:
        body = fh.read()
      extra = {"ContentType": content_type} if content_type else {}
      s3.put_object(Bucket=bucket, Key=key, Body=body, **extra)
      info("%s of %s -> %s/%s", os.path.basename(relpath), name, bucket, key)
      uploaded += 1
    except Exception as exc:            # pylint: disable=broad-except
      warning("could not upload %s of %s: %s", relpath, name, exc)
  if not uploaded:
    debug("no package in this build carries %s", relpath)
  return uploaded
