#!/usr/bin/env python3
"""Run: python3 -m unittest discover -s tests -v"""

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, BASE / 'scripts' / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


layout = load('layout_guard', 'check-asset-layout.py')
arch = load('arch_guard', 'check-code-architecture.py')


class RepoFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'Assets').mkdir()
        self.git('init', '-q')
        self.git('config', 'user.email', 'test@example.org')
        self.git('config', 'user.name', 'Test')

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.root,
                              check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def write(self, path, text='content'):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding='utf-8')
        return p

    def commit(self):
        self.git('add', '.')
        self.git('commit', '-qm', 'baseline')


class LayoutTests(RepoFixture):
    def test_vendor_files_can_exist_without_false_layout_violations(self):
        self.write('Assets/VendorSDK/Runtime.cs', 'public class Lib {}')
        self.write('Assets/VendorSDK/Prefab.prefab')
        self.commit()
        self.assertEqual(layout.check_project_file_locations(self.root), [])
        self.assertEqual(layout.check_git_vendor_changes(self.root), ([], None))

    def test_source_files_with_meta_are_allowed_including_src_meta(self):
        self.write('Assets/Src.meta', 'fileFormatVersion: 2')
        self.write('Assets/Src/Scripts.meta', 'fileFormatVersion: 2')
        self.write('Assets/Src/Scripts/Service.meta', 'fileFormatVersion: 2')
        self.write('Assets/Src/Scripts/Service/Traffic.cs', 'public class Traffic {}')
        self.write('Assets/Src/Scripts/Service/Traffic.cs.meta', 'fileFormatVersion: 2')
        self.assertEqual(layout.check_meta(self.root), [])
        self.assertEqual(layout.check_git_vendor_changes(self.root), ([], None))

    def test_legacy_scenes_and_root_assets_are_flagged(self):
        self.write('Assets/Scenes/SampleScene.unity')
        self.write('Assets/Readme.asset')
        violations = layout.check_project_file_locations(self.root)
        self.assertEqual(len(violations), 2)

    def test_existing_vendor_edit_is_detected(self):
        p = self.write('Assets/VendorSDK/Foo.cs')
        self.commit()
        p.write_text('changed')
        changes, err = layout.check_git_vendor_changes(self.root)
        self.assertIsNone(err)
        self.assertEqual(len(changes), 1)
        self.assertIn('Assets/VendorSDK/Foo.cs', changes[0])

    def test_moving_vendor_file_into_src_is_detected(self):
        self.write('Assets/VendorSDK/Foo.cs')
        self.commit()
        self.write('Assets/Src/Scripts/Integration.meta')
        dst = self.root / 'Assets/Src/Scripts/Integration/Foo.cs'
        dst.parent.mkdir(parents=True, exist_ok=True)
        self.git('mv', 'Assets/VendorSDK/Foo.cs', 'Assets/Src/Scripts/Integration/Foo.cs')
        changes, err = layout.check_git_vendor_changes(self.root)
        self.assertIsNone(err)
        self.assertTrue(any('Assets/VendorSDK/Foo.cs' in x for x in changes))

    def test_missing_source_meta_is_flagged(self):
        self.write('Assets/Src/Scripts/Service/Foo.cs')
        violations = layout.check_meta(self.root)
        self.assertTrue(any('Foo.cs' in v for v in violations))


class ArchitectureTests(RepoFixture):
    def test_ignores_comments_strings_raw_literals_and_preprocessor_else(self):
        example = '''
            // switch else case
            /* else switch */
            string a = "else switch case";
            string b = @"hello "" switch else""";
            var c = """case switch else""";
            char d = 's';
            #else
            if (data == null) throw new ArgumentNullException();
        '''
        result = arch.mask_non_code(example)
        self.assertEqual(arch.SYNTAX_RE.findall(result), [])

    def test_bans_switch_case_default_and_else(self):
        source = '''namespace Game.Service;
[Service] public sealed class Foo {
    void Run(int mode) { if (mode > 0) Start(); else Stop();
        switch (mode) { case 1: break; default: break; }
    }
}'''
        self.write('Assets/Src/Scripts/Service/Foo.cs', source)
        issues = arch.verify_sources(self.root)
        branches = [x for x in issues if 'BRANCH:' in x]
        self.assertEqual(len(branches), 4, issues)

    def test_manual_creation_of_annotated_service_is_rejected(self):
        self.write('Assets/Src/Scripts/Service/Factory.cs', '''namespace Game.Service;
[Service] class VehicleService {}
[Service] class Factory { void Build() { var x = new VehicleService(); } }
''')
        issues = arch.verify_sources(self.root)
        self.assertTrue(any("do not construct DI-managed 'VehicleService'" in x for x in issues), issues)

    def test_service_cannot_reference_integration(self):
        self.write('Assets/Src/Scripts/Integration/RCCPAdapter.cs',
                   'namespace Game.Integration; [Component] class RCCPAdapter {}')
        self.write('Assets/Src/Scripts/Service/GameService.cs',
                   'using Game.Integration;\nnamespace Game.Service;\n[Service] class GameService {}')
        issues = arch.verify_sources(self.root)
        self.assertTrue(any('BOUNDARY: Service must not reference project Integration' in x
                            for x in issues), issues)

    def test_service_cannot_use_unity_or_runtime_context(self):
        self.write('Assets/Src/Scripts/Service/GameService.cs',
                   'using UnityEngine;\nnamespace Game.Service;\n[Service] class GameService { '
                   'void Go() { RuntimeContext.Get<int>(); } }')
        issues = arch.verify_sources(self.root)
        self.assertTrue(any('UNITY:' in x for x in issues), issues)
        self.assertTrue(any('DI:' in x for x in issues), issues)

    def test_guard_if_and_annotated_service_are_valid(self):
        self.write('Assets/Src/Scripts/Service/Foo.cs', '''using System;
namespace Game.Service;
[Service]
public sealed class Foo {
    public int Go(object value) { if (value == null) throw new ArgumentNullException(); return 42; }
}''')
        self.assertEqual(arch.verify_sources(self.root), [])

    def test_direct_mono_behaviour_is_rejected(self):
        self.write('Assets/Src/Scripts/Controller/C.cs',
                   'namespace Game.Controller; class C : MonoBehaviour {}')
        self.assertTrue(any('AutowiredMonoBehaviour' in x for x in arch.verify_sources(self.root)))


class ConfigTests(RepoFixture):
    def test_custom_src_root_and_legacy_lists(self):
        self.write('.claude/unispring-skill.json',
                   '{"srcRoot": "Assets/Game", "scriptsRoot": "Assets/Game/Code", '
                   '"legacyProjectPrefixes": ["Assets/Old/"], "legacyProjectFiles": []}')
        self.write('Assets/Old/Level.unity')
        self.write('Assets/Readme.asset')  # Assets/ root project file is still flagged
        violations = layout.check_project_file_locations(self.root)
        self.assertEqual(len(violations), 2, violations)
        self.assertTrue(any('OUTSIDE Assets/Game' in v for v in violations), violations)
        self.write('Assets/Game/Code/Service/Foo.cs', 'class Foo { void F() { switch (1) {} } }')
        self.assertTrue(any('BRANCH:' in x for x in arch.verify_sources(self.root)))

    def test_composition_root_folder_name_is_configurable(self):
        self.write('.claude/unispring-skill.json', '{"compositionRoot": "Composition"}')
        self.write('Assets/Src/Scripts/Composition/Root.cs',
                   'using UnityEngine;\nnamespace Game.Composition; public static class Root '
                   '{ static void Go() { var c = ApplicationContext.Build(); } }')
        self.assertEqual(arch.verify_sources(self.root), [])

    def test_broken_config_is_an_error(self):
        self.write('.claude/unispring-skill.json', '[1, 2]')
        proc = subprocess.run([sys.executable, str(BASE / 'scripts' / 'check-asset-layout.py'),
                               '--root', str(self.root)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2, proc.stdout)


if __name__ == '__main__':
    unittest.main()
