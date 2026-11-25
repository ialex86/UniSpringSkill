"""Unit tests for module-first and legacy API-only subsystem boundaries."""
from test_guards import RepoFixture, load

subsystems = load('subsystem_guard', 'check-subsystem-boundaries.py')
arch = load('architecture_guard_for_subsystems', 'check-code-architecture.py')


class SubsystemBoundaryTests(RepoFixture):
    def module(self, name, with_asmdefs=True):
        if with_asmdefs:
            self.write(f'Assets/Src/Scripts/{name}/Api/{name}.Api.asmdef',
                       '{"name":"Game.' + name + '.Api","references":[]}')
            self.write(f'Assets/Src/Scripts/{name}/Internal/{name}.Runtime.asmdef',
                       '{"name":"Game.' + name + '.Runtime",'
                       '"references":["Game.' + name + '.Api"]}')
        self.write(f'Assets/Src/Scripts/{name}/Api/I{name}Api.cs',
                   f'namespace Game.{name}.Api; public interface I{name}Api {{}}')
        self.write(f'Assets/Src/Scripts/{name}/Internal/Service/{name}Service.cs',
                   f'namespace Game.{name}.Internal.Service; '
                   f'[Service] internal sealed class {name}Service {{}}')

    def test_modules_can_use_only_other_module_api(self):
        self.module('Environment')
        self.module('Traffic')
        self.write('Assets/Src/Scripts/Traffic/Internal/Service/Clock.cs', """
using Game.Environment.Api;
namespace Game.Traffic.Internal.Service;
[Service] internal sealed class Clock { private readonly IEnvironmentApi api;
    public Clock(IEnvironmentApi api) { this.api = api; } }
""")
        self.assertEqual(subsystems.verify_sources(self.root), [])
        self.assertEqual(arch.verify_sources(self.root), [])

    def kit(self):
        self.write('.claude/unispring-skill.json', '{"sharedKits": ["UiKit"]}')
        self.write('Assets/Src/Scripts/UiKit/Presentation/Game.UiKit.Presentation.asmdef',
                   '{"name":"Game.UiKit.Presentation","references":[]}')
        self.write('Assets/Src/Scripts/UiKit/Presentation/CatalogPopup.cs',
                   'namespace Game.UiKit.Presentation; public sealed class CatalogPopup {}')

    def test_presentation_may_use_the_shared_workshop_kit(self):
        self.module('Traffic')
        self.kit()
        self.write('Assets/Src/Scripts/Traffic/Presentation/TrafficMenu.cs', """
using Game.UiKit.Presentation;
namespace Game.Traffic.Presentation;
public sealed class TrafficMenu { private CatalogPopup popup; }
""")
        issues = subsystems.verify_sources(self.root)
        self.assertFalse(any('UiKit' in x or 'SHARED' in x for x in issues), issues)

    def test_core_layers_may_not_use_the_shared_workshop_kit(self):
        self.module('Traffic')
        self.kit()
        self.write('Assets/Src/Scripts/Traffic/Internal/Service/Clock.cs', """
using Game.UiKit.Presentation;
namespace Game.Traffic.Internal.Service;
[Service] internal sealed class Clock { private CatalogPopup popup; }
""")
        issues = subsystems.verify_sources(self.root)
        self.assertTrue(any('SHARED: a shared presentation kit' in x for x in issues), issues)

    def test_direct_other_module_service_rejected(self):
        self.module('Environment')
        self.module('Traffic')
        self.write('Assets/Src/Scripts/Traffic/Internal/Service/Clock.cs', """
using Game.Environment.Internal.Service;
namespace Game.Traffic.Internal.Service;
[Service] internal sealed class Clock { private EnvironmentService service; }
""")
        issues = subsystems.verify_sources(self.root)
        self.assertTrue(any('MODULE: cross-module reference' in x for x in issues), issues)

    def test_qualified_name_and_alias_cannot_bypass_api(self):
        self.module('Environment')
        self.module('Traffic')
        self.write('Assets/Src/Scripts/Traffic/Internal/Service/Other.cs', """
using Alias = Game.Environment.Internal.Service.EnvironmentService;
namespace Game.Traffic.Internal.Service;
[Service] internal class Other {
    Game.Environment.Internal.Service.EnvironmentService s;
}
""")
        issues = subsystems.verify_sources(self.root)
        self.assertGreaterEqual(len([x for x in issues if 'MODULE:' in x]), 2, issues)

    def test_module_api_cannot_depend_on_own_internal_service(self):
        self.module('Environment')
        self.write('Assets/Src/Scripts/Environment/Api/InvalidApi.cs', """
using Game.Environment.Internal.Service;
namespace Game.Environment.Api;
public interface IInvalidApi { EnvironmentService GetService(); }
""")
        issues = subsystems.verify_sources(self.root)
        self.assertTrue(any('API: public module API' in x for x in issues), issues)

    def test_other_runtime_assembly_reference_rejected(self):
        self.module('Environment')
        self.module('Traffic')
        self.write('Assets/Src/Scripts/Traffic/Internal/Traffic.Runtime.asmdef', """
{"name":"Game.Traffic.Runtime", "references":[
    "Game.Traffic.Api", "Game.Environment.Runtime"]}
""")
        issues = subsystems.verify_sources(self.root)
        self.assertTrue(any('ASMDEF: cross-module assembly dependency' in x for x in issues), issues)

    def test_api_asmdef_cannot_reference_own_internal(self):
        self.module('Environment')
        self.write('Assets/Src/Scripts/Environment/Api/Environment.Api.asmdef',
                   '{"name":"Game.Environment.Api","references":["Game.Environment.Runtime"]}')
        issues = subsystems.verify_sources(self.root)
        self.assertTrue(any('API assembly must not reference its own internal' in x for x in issues), issues)

    def test_missing_asmdefs_for_new_module_rejected(self):
        self.module('Environment', with_asmdefs=False)
        issues = subsystems.verify_sources(self.root)
        self.assertEqual(len([x for x in issues if 'requires separate' in x]), 2, issues)

    def test_legacy_layer_first_layout_still_supported(self):
        self.write('Assets/Src/Scripts/Api/Environment/IEnvironmentApi.cs',
                   'namespace Game.Environment.Api; public interface IEnvironmentApi {}')
        self.write('Assets/Src/Scripts/Service/Environment/EnvironmentService.cs',
                   'namespace Game.Environment.Internal.Service; [Service] class EnvironmentService {}')
        self.write('Assets/Src/Scripts/Service/Traffic/TrafficService.cs', """
using Game.Environment.Api;
namespace Game.Traffic.Internal.Service;
[Service] class TrafficService { private IEnvironmentApi api; }
""")
        self.assertEqual(subsystems.verify_sources(self.root), [])
        self.assertEqual(arch.verify_sources(self.root), [])

    def test_legacy_cross_module_dao_direct_dependency_rejected(self):
        self.write('Assets/Src/Scripts/Dao/Environment/DataDao.cs',
                   'namespace Game.Environment.Dao; public class DataDao {}')
        self.write('Assets/Src/Scripts/Service/Traffic/TrafficService.cs', """
using Game.Environment.Dao;
namespace Game.Traffic.Internal.Service;
[Service] class TrafficService { private DataDao dao; }
""")
        issues = subsystems.verify_sources(self.root)
        self.assertTrue(any('MODULE: cross-module reference' in x for x in issues), issues)

    def test_comments_and_strings_do_not_generate_false_positives(self):
        self.module('Environment')
        self.module('Traffic')
        self.write('Assets/Src/Scripts/Traffic/Internal/Service/Other.cs', """
namespace Game.Traffic.Internal.Service;
[Service] class Other { string text = "Game.Environment.Internal.Service";
// using Game.Environment.Internal.Service;
}
""")
        self.assertEqual(subsystems.verify_sources(self.root), [])
