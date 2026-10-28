import os, json, time, tempfile
d = tempfile.mkdtemp(); mc = os.path.join(d, "mc"); os.makedirs(os.path.join(mc, "versions"))
import cubeon.paths as P; P.MINECRAFT_DIR = mc
import cubeon.versions as V, cubeon.instances as I
V.MINECRAFT_DIR = mc
libs = [{"name": f"org.example:lib{i}:1.{i}", "downloads": {"artifact": {"path": f"a/{i}.jar", "sha1": "0"*40, "size": i, "url": "https://x/"+str(i)}}, "rules": [{"action": "allow"}]} for i in range(900)]
for n in range(40):
    vid = f"1.{n//4+8}.{n%4}"; p = os.path.join(mc, "versions", vid); os.makedirs(p)
    json.dump({"id": vid, "type": "release", "mainClass": "x", "libraries": libs, "arguments": {"game": [], "jvm": []}, "assetIndex": {"id": "1"}, "downloads": {}}, open(os.path.join(p, vid+".json"), "w"))
    open(os.path.join(p, vid+".jar"), "wb").write(b"x"*1024)
for i in range(5):
    t = time.perf_counter(); inst = V.get_installed_versions(); a = time.perf_counter()-t
    t = time.perf_counter(); I.list_installed(inst); b = time.perf_counter()-t
    print(f"scan {a*1000:.0f} ms ({len(inst)} versions) | describe {b*1000:.0f} ms")
