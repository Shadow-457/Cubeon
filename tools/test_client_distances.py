"""Distance option identification, optional packaging, and opt-in native injection checks."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
import json

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / 'mod/src/main'


@unittest.skipUnless(shutil.which('javac') and shutil.which('java'), 'JDK required')
class DistanceTests(unittest.TestCase):
    def test_translation_keys_and_unknown_layouts(self):
        with tempfile.TemporaryDirectory(prefix='cubeon-distances-') as temporary:
            folder = Path(temporary)
            files = {
                'net/minecraft/text/Text.java': '''package net.minecraft.text;
public class Text { private final Object content; public Text(Object value){content=value;}
public Object getContent(){return content;} }''',
                'net/minecraft/text/TranslatableTextContent.java': '''package net.minecraft.text;
public class TranslatableTextContent { private final String key;
public TranslatableTextContent(String value){key=value;} public String getKey(){return key;} }''',
                'Probe.java': '''import com.cubeon.client.ChunkDistanceOptions;
import net.minecraft.text.*;
public class Probe {
 public record Option(Text name) { public Text getName(){return name;} }
 static void check(boolean value,String why){if(!value)throw new AssertionError(why);}
 public static void main(String[] args) {
  for(String key:new String[]{"options.renderDistance","options.simulationDistance"})
   check(ChunkDistanceOptions.sodiumMinimum(new Option(new Text(new TranslatableTextContent(key))),5)==1,"Distance keys lower minimum independently of language");
  for(String key:new String[]{"options.biomeBlendRadius","options.framerateLimit","options.entityDistanceScaling"})
   check(ChunkDistanceOptions.sodiumMinimum(new Option(new Text(new TranslatableTextContent(key))),2)==2,"Other ranges retain minimum");
  check(ChunkDistanceOptions.sodiumMinimum(new Option(new Text("Render Distance")),2)==2,"Plain display text does not masquerade as a translated option");
  check(ChunkDistanceOptions.sodiumMinimum(new Object(),5)==5,"Unknown API fails open to native range");
  check(ChunkDistanceOptions.sodiumMinimum(null,2)==2,"Missing option preserves range");
 }
}'''}
            for name, value in files.items():
                path = folder/name
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text(value)
            sources = [*folder.rglob('*.java'),MAIN/'java-overlay-api-yarn/com/cubeon/client/ChunkDistanceOptions.java']
            result = subprocess.run(['javac','--release','17','-d',str(folder),*map(str,sources)],capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            result = subprocess.run(['java','-cp',str(folder),'Probe'],capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_packaged_optional_features(self):
        matrix = json.loads((ROOT/'mod/brackets.json').read_text())
        required = ['hud/HudFeatures','hud/ExtraHud','hud/HudReadings','ui/HudIcon',
                    'mixin/ChunkDistanceOptionsMixin','mixin/LocalSimulationDistanceMixin',
                    'mixin/SodiumDistanceMixin','mixin/SodiumLegacyDistanceMixin',
                    'mixin/AutoSprintMixin','mixin/ComboDamageMixin']
        for bracket in matrix['brackets']:
            name = matrix['jar_name'].replace('{version}',matrix['mod_version']).replace('{key}',bracket['key'])
            with self.subTest(version=bracket['key']),zipfile.ZipFile(ROOT/'assets/jars'/name) as jar:
                entries = set(jar.namelist())
                for value in required:
                    self.assertIn('com/cubeon/client/'+value+'.class',entries)
                self.assertNotIn('com/cubeon/client/mixin/CustomReticleMixin.class',entries)
                if bracket['key'] == matrix['brackets'][0]['key']:
                    code = subprocess.run(['javap','-p','-classpath',str(ROOT/'assets/jars'/name),
                                           'com.cubeon.client.mixin.SodiumLegacyDistanceMixin'],
                                          capture_output=True,text=True,timeout=60)
                    self.assertEqual(code.returncode,0,code.stdout+code.stderr)
                    self.assertIn('private static int cubeon$distanceMinimum',code.stdout,
                                  'Constructor HEAD handler must be static before super()')
                config = json.loads(jar.read('cubeon-client.mixins.json'))
                self.assertFalse(config['required'])
                self.assertNotIn('CustomReticleMixin',config['client'])
                for value in required:
                    if value.startswith('mixin/'):
                        self.assertIn(value.split('/')[1],config['client'])
                labels = json.loads(jar.read('assets/cubeon-client/lang/en_us.json'))
                for feature in ['clock','system','potions','coordinates','direction','biome','daylight','combo','sprint']:
                    self.assertIn('cubeonclient.hud.'+feature,labels)
                for feature in ['minimap','reticle']:
                    self.assertNotIn('cubeonclient.hud.'+feature,labels)

    @unittest.skipUnless(os.environ.get('CUBEON_DISTANCE_LEGACY'), 'Set CUBEON_DISTANCE_LEGACY to the isolated legacy constructor probe directory')
    def test_native_legacy_constructor(self):
        log = (Path(os.environ['CUBEON_DISTANCE_LEGACY'])/'probe.log').read_text(errors='replace')
        for key,minimum in [('options.renderDistance',1),('options.simulationDistance',1),('options.framerateLimit',2)]:
            self.assertIn(f'CUBEON_LEGACY_DISTANCE_VERIFIED {key}={minimum} max=32 step=1',log)
        self.assertNotIn('InvalidInjectionException',log)
        self.assertNotIn('VerifyError',log)

    @unittest.skipUnless(os.environ.get('CUBEON_DISTANCE_NATIVE'), 'Set CUBEON_DISTANCE_NATIVE to an isolated Minecraft game directory')
    def test_native_applied_mixins_and_local_simulation(self):
        profile = Path(os.environ['CUBEON_DISTANCE_NATIVE'])
        export = profile/'.mixin.out/class'
        def bytecode(name):
            result = subprocess.run(['javap','-c','-p','-classpath',str(export),name],capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            return result.stdout
        options = bytecode('net.minecraft.class_315')
        self.assertIn('cubeon$renderMinimum',options)
        self.assertIn('cubeon$simulationMinimum',options)
        builder = bytecode('net.caffeinemc.mods.sodium.client.gui.SodiumConfigBuilder')
        self.assertIn('cubeon$renderMinimum',builder)
        self.assertIn('cubeon$simulationMinimum',builder)
        # Both injected handlers return 1. Their invocation precedes setRange,
        # while unrelated ranges retain their original arguments.
        for name in ['renderMinimum','simulationMinimum']:
            tail = builder[builder.rindex('cubeon$'+name):]
            body = tail[:tail.index('ireturn')]
            self.assertIn('iconst_1',body)
        server = bytecode('net.minecraft.class_1132')
        self.assertIn('cubeon$localSimulationMinimum',server)
        log = (profile/'logs/latest.log').read_text(errors='replace')
        self.assertIn('Changing simulation distance to 1',log)
        saved = (profile/'options.txt').read_text()
        self.assertIn('renderDistance:1\n',saved)
        self.assertIn('simulationDistance:1\n',saved)


if __name__ == '__main__':
    unittest.main()
