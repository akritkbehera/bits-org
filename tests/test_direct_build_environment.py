# SPDX-FileCopyrightText: 2026 CERN
# SPDX-License-Identifier: GPL-3.0-or-later
import subprocess
import tempfile
import unittest
from collections import OrderedDict
from pathlib import Path

from bits_helpers.hashing import storeHashes
from bits_helpers.initdotsh import generate_initdotsh
from bits_helpers.recipe import SpecError, validateSpec


def package(name, requires=(), **kwargs):
    spec = dict(package=name, version='1', revision='rev', hash='hash',
                commit_hash='commit', requires=list(requires))
    spec.update(kwargs)
    return spec


class DirectBuildEnvironmentTest(unittest.TestCase):
    def test_only_immediate_dependencies_are_activated(self):
        with tempfile.TemporaryDirectory() as tmp:
            specs = {'App': package('App', ['Tool'], build_environment='direct'),
                     'Tool': package('Tool', ['Leaf'], env={'TOOL_SETTING': 'enabled'}),
                     'Leaf': package('Leaf')}
            for name in ['Tool', 'Leaf']:
                root = Path(tmp, 'test', name, '1-rev')
                (root / 'bin').mkdir(parents=True)
                (root / 'lib').mkdir()
            script = generate_initdotsh('App', specs, 'test', workDir=tmp)
            script += '\nprintf "%s\\n" "$PATH" "$LD_LIBRARY_PATH" "${LEAF_ROOT-unset}" "$TOOL_SETTING"\n'
            result = subprocess.check_output(['bash', '-e'], input=script, text=True,
                                             env={'PATH': '/usr/bin:/bin'})
            self.assertIn('/Tool/1-rev/bin', result)
            self.assertIn('/Tool/1-rev/lib', result)
            self.assertNotIn('/Leaf/', result)
            self.assertIn('unset\nenabled', result)
            self.assertNotIn('/etc/profile.d/init.sh', script)

    def test_runtime_still_sources_dependency_init(self):
        specs = {'App': package('App', ['Tool'], build_environment='direct'),
                 'Tool': package('Tool')}
        runtime = generate_initdotsh('App', specs, 'test', post_build=True)
        self.assertIn('/Tool/1-rev/etc/profile.d/init.sh', runtime)

    def test_shared_family_forced_revision_and_not_needed(self):
        specs = {'App': package('App', ['Tool', 'Skipped'], build_environment='direct'),
                 'Tool': package('Tool', architecture='share', pkg_family='external', force_revision='', revision=''),
                 'Skipped': package('Skipped', not_needed=True)}
        output = generate_initdotsh('App', specs, 'test')
        self.assertIn('export TOOL_ROOT="$WORK_DIR/share"/external/Tool/1', output)
        self.assertNotIn('SKIPPED_ROOT', output)

    def test_reused_dependency_uses_deployed_root_without_sourcing(self):
        specs = {'App': package('App', ['Tool'], build_environment='direct'),
                 'Tool': package('Tool', reuse_module_id='Tool/1-deployed')}
        output = generate_initdotsh('App', specs, 'test', reuse_cvmfs_base='/deployment/Packages')
        self.assertIn('export TOOL_ROOT=/deployment/Packages/Tool/1-deployed', output)
        self.assertNotIn('/etc/profile.d/init.sh', output)

    def test_reused_dependency_environment_executes_without_deployed_init(self):
        with tempfile.TemporaryDirectory() as tmp:
            deployment = Path(tmp, 'deployment')
            tool = deployment / 'Tool/1-deployed'
            (tool / 'bin').mkdir(parents=True)
            specs = {'App': package('App', ['Tool'], build_environment='direct'),
                     'Tool': package('Tool', reuse_module_id='Tool/1-deployed',
                                     env={'SETTING': '${TOOL_ROOT}/data'})}
            script = generate_initdotsh('App', specs, 'test', workDir=tmp,
                                        reuse_cvmfs_base=str(deployment), cmake_prefix_env=True)
            script += '\nprintf "%s\\n" "$TOOL_ROOT" "$SETTING" "$CMAKE_PREFIX_PATH"\n'
            result = subprocess.check_output(['bash', '-e'], input=script, text=True,
                                             env={'PATH': '/usr/bin:/bin'})
            self.assertEqual(result.splitlines(), [str(tool), str(tool / 'data'), str(tool)])

    def test_mode_changes_hash_only_when_enabled(self):
        def identity(mode):
            spec = package('App', is_devel_pkg=False, recipe='true', scm_refs={})
            if mode is not None:
                spec['build_environment'] = mode
            storeHashes('App', {'App': spec}, considerRelocation=False)
            return spec['remote_revision_hash']
        self.assertEqual(identity(None), identity('recursive'))
        self.assertNotEqual(identity(None), identity('direct'))

    def test_invalid_mode_is_rejected(self):
        spec = OrderedDict(package='App', version='1', build_environment='typo')
        with self.assertRaises(SpecError):
            validateSpec(spec)

    def test_direct_dependency_settings_are_ordered_before_consumers(self):
        specs = {'App': package('App', ['Consumer', 'Tool'], build_environment='direct'),
                 'Consumer': package('Consumer', ['Tool'], env={'SETTING': '${TOOL_ROOT}/data'}),
                 'Tool': package('Tool')}
        output = generate_initdotsh('App', specs, 'test')
        self.assertLess(output.index('export TOOL_ROOT='), output.index('export SETTING='))

    def test_large_dependency_chain_does_not_recurse_in_python(self):
        specs = {'App': package('App', ['Tool', 'Other'], build_environment='direct'),
                 'Other': package('Other')}
        for index in range(2000):
            name = 'Tool' if index == 0 else 'D%d' % index
            requirements = ['D%d' % (index + 1)] if index < 1999 else []
            specs[name] = package(name, requirements)
        output = generate_initdotsh('App', specs, 'test')
        self.assertIn('export TOOL_ROOT=', output)
        self.assertNotIn('export D1_ROOT=', output)
        self.assertLess(len(output), 10000)

    def test_path_settings_and_modules_mode_are_executed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp, 'test', 'Tool', '1-rev')
            (root / 'include').mkdir(parents=True)
            (root / 'lib/python3.12/site-packages').mkdir(parents=True)
            specs = {'App': package('App', ['Tool'], build_environment='direct'),
                     'Tool': package('Tool', append_path={'EXTRA_PATH': '/append'},
                                     prepend_path={'EXTRA_PATH': '$TOOL_ROOT/include'})}
            script = generate_initdotsh('App', specs, 'test', workDir=tmp, from_modules=True)
            script += '\nprintf "%s\\n" "$EXTRA_PATH" "$PYTHONPATH" "$CMAKE_PREFIX_PATH"\n'
            result = subprocess.check_output(['bash', '-e'], input=script, text=True,
                                             env={'PATH': '/usr/bin:/bin'})
            self.assertIn(str(root / 'include') + '::/append', result)
            self.assertIn(str(root / 'lib/python3.12/site-packages'), result)
            self.assertIn(str(root), result)
