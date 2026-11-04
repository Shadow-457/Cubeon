"""Run the production wing fallback contract; --targets audits all real game hooks."""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
JAVA = ROOT / 'mod/src/main/java/com/cubeon/client'

HARNESS = r'''
import com.cubeon.client.cosmetics.*;
import java.nio.file.*;
import java.util.*;

public class ElytraTest {
    static void check(boolean ok, String message) {
        if (!ok) throw new AssertionError(message);
    }
    static class VanillaWings { }
    public static void main(String[] args) throws Exception {
        String text = Files.readString(Path.of(args[0]));
        var catalog = CosmeticCatalog.Catalog.parse(text);
        var wings = catalog.get("back_void_wings");
        var small = catalog.get("back_void_wings_small");
        var flat = wings.forWingDepth(false);
        var pack = catalog.get("back_gear_pack");
        Object player = new Object(), peer = new Object();
        check(!CosmeticElytra.consume(player), "No prior draw keeps vanilla");
        for (var item : List.of(wings, small, flat)) {
            check(CosmeticElytra.ready(item), "Bundled wing art must be ready: " + item.id);
            CosmeticElytra.begin(player);
            CosmeticElytra.drawn(item);
            check(CosmeticElytra.consume(player), "Ready drawn wings replace elytra");
            check(!CosmeticElytra.consume(player), "No stale replacement next pass");
        }
        for (String filename : List.of("missing.png", "corrupt.png")) {
            var missing = CosmeticCatalog.Catalog.parse(text.replace(wings.texture, filename)).get(wings.id);
            check(!CosmeticElytra.ready(missing), "Missing/invalid artwork keeps vanilla");
            CosmeticElytra.begin(player); CosmeticElytra.drawn(missing);
            check(!CosmeticElytra.consume(player), "Missing image cannot hide vanilla");
        }
        CosmeticElytra.begin(player); CosmeticElytra.drawn(pack);
        check(!CosmeticElytra.consume(player), "Backpacks cannot replace elytra");
        CosmeticElytra.begin(player); CosmeticElytra.drawn(null);
        check(!CosmeticElytra.consume(player), "Unknown ids keep vanilla");
        CosmeticElytra.begin(player); CosmeticElytra.drawn(wings);
        check(!CosmeticElytra.consume(peer), "Another player's draw cannot hide this elytra");
        CosmeticElytra.begin(player); CosmeticElytra.drawn(wings);
        CosmeticElytra.begin(peer);
        check(!CosmeticElytra.consume(peer), "Hidden/empty next player clears prior wings");
        CosmeticElytra.begin(player); CosmeticElytra.drawn(wings);
        boolean[] otherThread = {true};
        Thread worker = new Thread(() -> otherThread[0] = CosmeticElytra.consume(player));
        worker.start(); worker.join();
        check(!otherThread[0] && CosmeticElytra.consume(player), "Draw passes remain thread local");
        Object before = new Object(), cosmetics = new Object(), after = new Object();
        var vanilla = new VanillaWings();
        var layers = new ArrayList<>(List.of(before, vanilla, after, cosmetics));
        check(CosmeticElytra.order(layers, cosmetics, VanillaWings.class), "Register replacement order");
        check(layers.equals(List.of(before, cosmetics, vanilla, after)), "Draw cosmetic wings immediately before vanilla");
        CosmeticElytra.order(layers, cosmetics, VanillaWings.class);
        check(layers.equals(List.of(before, cosmetics, vanilla, after)), "Repeated registration order is stable");
        check(!CosmeticElytra.order(new ArrayList<>(List.of(cosmetics)), cosmetics, VanillaWings.class),
                "Absent vanilla layer cannot enable replacement");
        System.out.println("Giant/Small/flat wings, fallback art, packs, identity, pass reset and registration passed.");
    }
}
'''


def run_contract():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        harness = root / 'ElytraTest.java'
        harness.write_text(HARNESS)
        sources = [JAVA / 'Json.java'] + [JAVA / 'cosmetics' / (name + '.java')
                   for name in ('CosmeticCatalog', 'CosmeticGeometry', 'CosmeticElytra')]
        subprocess.run(['javac', '--release', '17', '-d', folder,
                        *map(str, sources), str(harness)], check=True, timeout=60)
        art = root / 'assets/cubeon-client/textures/cosmetics'
        art.mkdir(parents=True)
        for source in (ROOT / 'assets/cosmetics').glob('*.png'):
            shutil.copyfile(source, art / source.name)
        (art / 'corrupt.png').write_bytes(b'not a PNG')
        subprocess.run(['java', '-cp', folder, 'ElytraTest',
                        str(ROOT / 'assets/cosmetics/catalog.json')], check=True, timeout=30)


def audit_targets():
    base = ROOT / 'mod/.gradle/loom-cache/minecraftMaven/net/minecraft'
    paths = list(base.glob('*/*/*.jar'))
    matrix = json.loads((ROOT / 'mod/brackets.json').read_text())['brackets']
    config = json.loads((ROOT / 'mod/src/main/resources/cubeon-client.mixins.json').read_text())
    assert all(hook in config['client'] for hook in ('CosmeticLayersAccessor', 'CosmeticElytraMixin'))
    for bracket in matrix:
        version = bracket['compile_against']
        game = next(p for p in paths if p.parent.name.split('-net.fabricmc')[0] == version
                    and '-sources' not in p.name)
        era = next(o for o in bracket['overlays'] if o.startswith('cosmetics-'))
        native = bracket['mappings'] == 'none'
        package = 'net.minecraft.client.renderer.entity' if native else 'net.minecraft.client.render.entity'
        target = package + ('.layers.WingsLayer' if native else '.feature.ElytraFeatureRenderer')
        source = (ROOT / f'mod/src/main/java-overlay-{era}/com/cubeon/client/mixin/CosmeticElytraMixin.java').read_text()
        descriptor = re.search(r'@Inject\(method = "(\w+)(\([^"]+\)V)"', source)
        assert descriptor, version
        javap = subprocess.check_output(['javap', '-p', '-s', '-classpath', str(game), target], text=True, timeout=30)
        assert 'descriptor: ' + descriptor[2] in javap, f'{version}: exact concrete render hook missing'
        assert f' {descriptor[1]}(' in javap, f'{version}: render method missing'
        renderer = subprocess.check_output(['javap', '-p', '-classpath', str(game), package + '.LivingEntityRenderer'], text=True, timeout=30)
        field = 'layers' if native else 'features'
        assert re.search(r'java.util.List[^\n]*\b' + field + ';', renderer), f'{version}: layer list accessor missing'
        registration = (ROOT / f'mod/src/main/java-overlay-{era}/com/cubeon/client/cosmetics/CosmeticsClient.java').read_text()
        assert target + '.class' in registration and 'cosmetics.enableElytraReplacement()' in registration
        print(f'{version}: concrete wing hook and registration layer list passed.', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--targets', action='store_true')
    args = parser.parse_args()
    run_contract()
    if args.targets:
        audit_targets()
