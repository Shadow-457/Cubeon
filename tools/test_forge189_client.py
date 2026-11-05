"""Verify the shipped Forge port; --targets checks real SRG calls and ASM hooks."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import zipfile
from unittest.mock import patch

PLAYER_HOME = Path.home()
import _sandbox_home  # noqa: F401; before Cubeon imports
_sandbox_home.isolate()
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cubeon import cubeonfriends

JAR = ROOT / "assets/jars/cubeon-client-forge-1.8.9.jar"

TARGET_TEST = r'''
import com.cubeon.forge.CameraTransformer;
import java.io.*;
import java.util.*;
import org.objectweb.asm.*;
import org.objectweb.asm.tree.*;
import org.objectweb.asm.tree.analysis.*;
public class ForgeTargets {
    static final Map<String,ClassNode> cache = new HashMap<>();
    static ClassNode node(String name) throws Exception {
        if (cache.containsKey(name)) return cache.get(name);
        InputStream in = ForgeTargets.class.getClassLoader().getResourceAsStream(name + ".class");
        if (in == null) throw new AssertionError("Missing runtime class: " + name);
        ClassNode c = new ClassNode(); new ClassReader(in).accept(c, 0); in.close(); cache.put(name,c); return c;
    }
    static boolean owned(String name) {
        return name.startsWith("net/minecraft/") || name.startsWith("net/minecraftforge/") || name.startsWith("com/cubeon/");
    }
    static boolean member(String owner, String name, String desc, boolean method, Set<String> visited) throws Exception {
        if (!visited.add(owner)) return false;
        if (owner.startsWith("java/")) {
            Class<?> c=Class.forName(owner.replace('/','.'));
            if(method) { for(java.lang.reflect.Method m:c.getDeclaredMethods()) if(m.getName().equals(name) && Type.getMethodDescriptor(m).equals(desc)) return true; }
            else { for(java.lang.reflect.Field f:c.getDeclaredFields()) if(f.getName().equals(name) && Type.getDescriptor(f.getType()).equals(desc)) return true; }
            return c.getSuperclass()!=null && member(c.getSuperclass().getName().replace('.','/'),name,desc,method,visited);
        }
        ClassNode c = node(owner);
        if (method) { for (MethodNode m:c.methods) if(m.name.equals(name) && m.desc.equals(desc)) return true; }
        else { for (FieldNode f:c.fields) if(f.name.equals(name) && f.desc.equals(desc)) return true; }
        if (name.equals("<init>")) return false;
        if(c.superName!=null && member(c.superName,name,desc,method,visited)) return true;
        for(String parent:c.interfaces) if(member(parent,name,desc,method,visited)) return true;
        return false;
    }
    public static void main(String[] args) throws Exception {
        int references=0, hooks=0;
        try(java.util.jar.JarFile jar=new java.util.jar.JarFile(args[0])) {
            Enumeration<java.util.jar.JarEntry> entries=jar.entries();
            while(entries.hasMoreElements()) {
                String name=entries.nextElement().getName(); if(!name.endsWith(".class")) continue;
                ClassNode c=node(name.substring(0,name.length()-6));
                for(MethodNode m:c.methods) for(AbstractInsnNode instruction:m.instructions.toArray()) {
                    String owner=null, target=null, desc=null; boolean method=false;
                    if(instruction instanceof MethodInsnNode) { MethodInsnNode n=(MethodInsnNode)instruction; owner=n.owner;target=n.name;desc=n.desc;method=true; }
                    if(instruction instanceof FieldInsnNode) { FieldInsnNode n=(FieldInsnNode)instruction;owner=n.owner;target=n.name;desc=n.desc; }
                    if(owner!=null && owned(owner)) {
                        if(!member(owner,target,desc,method,new HashSet<String>())) throw new AssertionError(c.name+" -> "+owner+"."+target+desc);
                        references++;
                    }
                }
            }
        }
        CameraTransformer transformer=new CameraTransformer();
        for(String name:new String[]{"net.minecraft.entity.Entity","net.minecraft.client.renderer.EntityRenderer",
                "net.minecraft.client.model.ModelPlayer","net.minecraft.client.multiplayer.PlayerControllerMP"}) {
            byte[] original=new ClassReader(name).b;
            byte[] changed=transformer.transform(name,name,original);
            if(Arrays.equals(original,changed)) throw new AssertionError("No hook in "+name);
            ClassNode c=new ClassNode();new ClassReader(changed).accept(c,ClassReader.EXPAND_FRAMES);
            for(MethodNode m:c.methods) {
                if((m.access & (Opcodes.ACC_ABSTRACT|Opcodes.ACC_NATIVE))==0) new Analyzer<BasicValue>(new BasicVerifier()).analyze(c.name,m);
                for(AbstractInsnNode n:m.instructions.toArray()) if(n instanceof MethodInsnNode && ((MethodInsnNode)n).owner.equals("com/cubeon/forge/RenderHooks")) hooks++;
            }
        }
        if(hooks<12) throw new AssertionError("Incomplete camera/emote/blur hooks: "+hooks);
        byte[] untouched=new ClassReader("net.minecraft.client.gui.GuiButton").b;
        if(transformer.transform("x","net.minecraft.client.gui.GuiButton",untouched)!=untouched) throw new AssertionError("Unrelated class rewritten");
        System.out.println("Verified "+references+" runtime references and "+hooks+" camera/emote/blur hooks against Forge 1.8.9 SRG.");
    }
}
'''


def check_native(args, temp, profile):
    """Boot real Forge/CSL/client in an isolated virtual display, without captures."""
    from cubeon import launch
    assert shutil.which("Xvfb"), "Native check needs Xvfb"
    assert launch.java_major_version(str(args.java8)) == 8, "Native check needs Java 8"
    game = Path(temp) / "game"
    (game / "mods").mkdir(parents=True)
    for source in Path(profile).glob("*.jar"):
        shutil.copy2(source, game / "mods" / source.name)
    (game / "options.txt").write_text("fullscreen:false\nrenderDistance:2\nmaxFps:30\n")
    options = {"username": "ForgeProbe", "uuid": "0123456789abcdef0123456789abcdef", "token": "0",
               "executablePath": str(args.java8.resolve()), "gameDirectory": str(game),
               "customResolution": True, "resolutionWidth": "640", "resolutionHeight": "480",
               "jvmArguments": ["-Xmx1G", "-Xms256M", "-Duser.home=" + temp]}
    command = launch.mll.command.get_minecraft_command(args.forge_version, str(args.minecraft_dir), options)
    output = ROOT / "build/forge-1.8.9"
    output.mkdir(parents=True, exist_ok=True)
    log_path = output / "native-forge.log"
    display = subprocess.Popen(["Xvfb", "-displayfd", "1", "-screen", "0", "800x600x24"],
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    process = None
    try:
        number = display.stdout.readline().strip()
        assert number.isdigit(), "Virtual display did not start"
        env = dict(os.environ, DISPLAY=":" + number, HOME=temp, USERPROFILE=temp)
        for key in ("LIBGL_ALWAYS_SOFTWARE", "GALLIUM_DRIVER", "CUBEON_GPU_RESTARTS"):
            env.pop(key, None)
        with log_path.open("w") as log:
            process = subprocess.Popen(command, cwd=game, env=env, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            deadline = time.monotonic() + 120
            while True:
                assert process.poll() is None, log_path.read_text(errors="replace")[-10000:]
                assert time.monotonic() < deadline, log_path.read_text(errors="replace")[-10000:]
                content = log_path.read_text(errors="replace")
                loaded = content.rfind("Forge Mod Loader has successfully loaded")
                if loaded >= 0 and content.rfind("Created:") > loaded \
                        and "Transformed Forge v1 target net/minecraft/client/resources/SkinManager" in content \
                        and "FMLFileResourcePack:Cubeon Client" in content:
                    break
                time.sleep(.25)
            time.sleep(1)
            assert process.poll() is None, log_path.read_text(errors="replace")[-10000:]
        print("Real Forge 1.8.9 Java 8 startup, CSL skin hooks and Cubeon Client loading passed; no captures.")
    finally:
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=10)
        display.terminate()
        display.wait(timeout=10)
        display.stdout.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets", action="store_true")
    parser.add_argument("--download-csl", action="store_true", help="Verify the public CSL download and isolated Forge staging")
    parser.add_argument("--native", action="store_true", help="With --download-csl: verify actual Java 8 startup without captures")
    parser.add_argument("--java8", type=Path, default=PLAYER_HOME / ".cubeon_launcher/runtimes/8/bin/java")
    parser.add_argument("--forge-version", default="1.8.9-forge-11.15.1.2318-1.8.9")
    parser.add_argument("--minecraft-dir", type=Path, default=PLAYER_HOME / ".cubeon_minecraft")
    args = parser.parse_args()
    if args.native and not args.download_csl:
        parser.error("--native requires --download-csl")
    with zipfile.ZipFile(JAR) as archive:
        names = archive.namelist()
        assert len(names) == len(set(names))
        assert "fabric.mod.json" not in names
        metadata = json.loads(archive.read("mcmod.info"))
        assert metadata[0]["modid"] == "cubeonclient" and metadata[0]["mcversion"] == "1.8.9"
        assert b"FMLCorePlugin: com.cubeon.forge.CameraPlugin" in archive.read("META-INF/MANIFEST.MF")
        assert not any(n.startswith("net/minecraft/") for n in names)
        for name in names:
            if name.endswith(".class"):
                assert int.from_bytes(archive.read(name)[6:8], "big") <= 52, name
    with tempfile.TemporaryDirectory(prefix="forge189-check-") as temp:
        from cubeon import jre, launch, mod_loaders
        java8, java21 = str(Path(temp) / "java8"), str(Path(temp) / "java21")
        Path(java8).touch()
        Path(java21).touch()
        with patch.object(launch, "find_java", return_value=java21), \
                patch.object(launch, "_java_home_binaries", return_value=[]), \
                patch.object(launch.mll.java_utils, "find_system_java_versions", return_value=[]), \
                patch.object(jre, "installed_runtimes", return_value={8: java8}), \
                patch.object(launch, "java_major_version", side_effect=lambda path: {java8: 8, java21: 21}.get(path)):
            assert launch.find_java_for_version("1.8.9-forge-11.15.1.2318-1.8.9", java21) == java8
            assert jre.java_status("1.8.9-forge", java21)["ok"]
        with patch.object(launch, "find_java_for_version", return_value=java21), \
                patch.object(launch, "java_major_version", return_value=21):
            assert jre.java_status("1.8.9-forge", java21) == {"ok": False, "required": 8, "found": 21, "exact": True}
            assert jre.java_status("1.8.9", java21)["ok"]
            try:
                mod_loaders.loader_java("1.8.9", "forge")
            except RuntimeError as error:
                assert "requires Java 8" in str(error)
            else:
                raise AssertionError("Forge installer accepted Java 21")
        print("Forge 1.8.9 exact Java 8 selection, download preflight and installer rejection passed.")
        profile = Path(temp) / "mods"
        profile.mkdir()
        (profile / "cubeon-client-stale.jar").write_bytes(b"old")
        (profile / "user-mod.jar").write_bytes(b"user")
        assert cubeonfriends.find_jar("1.8.9", "forge") == str(JAR)
        assert cubeonfriends.ensure_installed("1.8.9-forge-11.15.1.2318-1.8.9", "forge", str(profile))
        installed = profile / JAR.name
        assert hashlib.sha256(installed.read_bytes()).digest() == hashlib.sha256(JAR.read_bytes()).digest()
        assert not (profile / "cubeon-client-stale.jar").exists()
        assert (profile / "user-mod.jar").read_bytes() == b"user"
        assert not cubeonfriends.ensure_installed("1.8.8", "forge", str(profile))
        assert not installed.exists()
        assert cubeonfriends.find_jar("1.8.9", "fabric") is None
        assert cubeonfriends.find_jar("1.8.9", "neoforge") is None
        if args.download_csl:
            from cubeon import csl, mod_dependencies, mods
            result = csl.ensure_ready("1.8.9", "forge", version_id="1.8.9-forge-check")
            assert result["installed"], result
            assert csl.is_installed("1.8.9", "forge", "1.8.9-forge-check")
            active = mods.get_profile_dir("1.8.9", "forge", "1.8.9-forge-check")
            assert cubeonfriends.ensure_installed("1.8.9", "forge", active)
            with patch.object(mods, "get_mod_download", side_effect=AssertionError("Clean Forge profile requested network")):
                report = mod_dependencies.run_dependency_doctor(
                    "1.8.9", "forge", version_id="1.8.9-forge-check", runtime_versions={"java": 8})
            assert report == {"checked": 2, "fixed": [], "unfixed": []}, report
            print("Forge 1.8.9 CSL download and staging:", result["detail"])
            print("Real CSL universal bootstrap and Cubeon Client passed the prelaunch Doctor gate.")
            if args.native:
                check_native(args, temp, active)
        if args.targets:
            work = ROOT / "build/forge-1.8.9"
            # FML remaps Forge's own Notch descriptors to SRG at runtime too.
            with zipfile.ZipFile(work / "inputs/mcp-srg.zip") as archive:
                mapping = Path(temp) / "notch-srg.srg"
                mapping.write_bytes(archive.read("joined.srg"))
            forge = Path(temp) / "forge-srg.jar"
            subprocess.run([shutil.which("java"), "-jar", str(work / "inputs/specialsource.jar"), "--quiet", "--stable",
                "--in-jar", str(work / "inputs/forge-universal.jar"), "--out-jar", str(forge), "--srg-in", str(mapping)], check=True)
            source = Path(temp) / "ForgeTargets.java"
            source.write_text(TARGET_TEST)
            libraries = args.minecraft_dir / "libraries"
            classpath = os.pathsep.join(map(str, [JAR, work / "minecraft-srg.jar", forge,
                libraries / "org/ow2/asm/asm-debug-all/5.2/asm-debug-all-5.2.jar",
                libraries / "net/minecraft/launchwrapper/1.12/launchwrapper-1.12.jar"]))
            subprocess.run([shutil.which("javac"), "--release", "8", "-cp", classpath, "-d", temp, str(source)], check=True)
            subprocess.run([shutil.which("java"), "-cp", temp + os.pathsep + classpath, "ForgeTargets", str(JAR)], check=True)
    print("Forge 1.8.9 jar, exact loader routing, staging and stale cleanup passed.")


if __name__ == "__main__":
    main()
