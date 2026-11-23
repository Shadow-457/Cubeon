#!/usr/bin/env python3
"""Plain-JDK contracts for shared peer profiles, skins and Tab badges."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from test_mod_bridge import find_jdk  # noqa: E402
from test_mod_compile import STUBS  # noqa: E402


HARNESS = r'''
package com.cubeon.client.skins;

import java.io.ByteArrayInputStream;
import java.lang.reflect.Field;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLConnection;
import java.net.URLStreamHandler;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import com.cubeon.client.TabListTag;
import net.minecraft.client.Minecraft;
import net.minecraft.network.chat.Component;
import net.minecraft.network.chat.MutableComponent;

public final class PeerSkinTest {
    private static final String ID = "a".repeat(64);
    private static final String BROKEN_ID = "b".repeat(64);
    private static final java.util.Set<String> absent = java.util.concurrent.ConcurrentHashMap.newKeySet();
    private static final AtomicInteger requests = new AtomicInteger();
    private static final CountDownLatch started = new CountDownLatch(1);
    private static final CountDownLatch release = new CountDownLatch(1);
    private static final AtomicLong clock = new AtomicLong(1_000_000_000L);

    private static byte[] png() {
        byte[] bytes = new byte[24];
        int[] signature = {0x89,0x50,0x4e,0x47,0x0d,0x0a,0x1a,0x0a};
        for (int i=0;i<signature.length;i++) bytes[i]=(byte)signature[i];
        bytes[19]=64; bytes[23]=64;
        return bytes;
    }

    private static void settled(String key) throws Exception {
        Field field = RemoteSkins.class.getDeclaredField("CACHE"); field.setAccessible(true);
        long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(2);
        while (System.nanoTime() < deadline) {
            synchronized (RemoteSkins.class) {
                Object entry = ((Map<?,?>)field.get(null)).get(key.toLowerCase(java.util.Locale.ROOT));
                if (entry != null) {
                    var pending = entry.getClass().getDeclaredMethod("pending"); pending.setAccessible(true);
                    if (!(boolean)pending.invoke(entry)) return;
                }
            }
            Thread.sleep(2);
        }
        throw new AssertionError("Peer skin lookup did not settle: " + key);
    }

    public static void main(String[] args) throws Exception {
        Field clockField = RemoteSkins.class.getDeclaredField("clock"); clockField.setAccessible(true);
        clockField.set(null, (java.util.function.LongSupplier)clock::get);
        URL.setURLStreamHandlerFactory(protocol -> !protocol.equals("https") ? null : new URLStreamHandler() {
            protected URLConnection openConnection(URL url) {
                if (!url.getHost().equals("cubeon-skins.hamza-457-shahbaz.workers.dev"))
                    throw new AssertionError("Unexpected host " + url);
                return new HttpURLConnection(url) {
                    public void connect(){} public void disconnect(){} public boolean usingProxy(){return false;}
                    public int getResponseCode() {
                        requests.incrementAndGet(); started.countDown();
                        try { if (!release.await(5, TimeUnit.SECONDS)) throw new AssertionError("render waited for network"); }
                        catch (InterruptedException error) { throw new RuntimeException(error); }
                        if (url.getPath().contains("limited")) return 429;
                        if (url.getPath().contains("unknown")) return 404;
                        if (url.getPath().endsWith(BROKEN_ID) || absent.contains(url.getPath())) return 404;
                        return 200;
                    }
                    public String getHeaderField(String name) { return name.equals("Retry-After") ? "3600" : null; }
                    public java.io.InputStream getInputStream() {
                        if (url.getPath().startsWith("/skins/textures/")) return new ByteArrayInputStream(png());
                        String name = url.getPath().substring("/skins/".length(), url.getPath().length()-5);
                        String claimed = name.equals("mismatch") ? "SomeoneElse" : name;
                        String kind = name.equals("defaultskin") ? "cape" : "slim";
                        String id = name.equals("broken") ? BROKEN_ID : ID;
                        String body = name.equals("malformed") ? "{}" :
                                "{\"username\":\""+claimed+"\",\"textures\":{\""+kind+"\":\""+id+"\"}}";
                        return new ByteArrayInputStream(body.getBytes(StandardCharsets.UTF_8));
                    }
                };
            }
        });

        com.cubeon.client.Bridge.get(); // Exclude one-time bridge class initialization from frame timing.
        Component displayed = Component.literal("[Team] Remote");
        long before = System.nanoTime();
        if (TabListTag.decorate("Remote", displayed) != displayed)
            throw new AssertionError("unconfirmed Tab row must keep its original component");
        if (System.nanoTime()-before > TimeUnit.MILLISECONDS.toNanos(100)) throw new AssertionError("render path blocked");
        if (!started.await(2, TimeUnit.SECONDS)) throw new AssertionError("lookup did not start");
        release.countDown(); settled("Remote");
        RemoteSkins.Skin skin = RemoteSkins.get("Remote");
        if (skin == null || !skin.slim() || !ID.equals(skin.id()) || skin.png().length != 24)
            throw new AssertionError("valid slim skin was not published");
        Component tagged = TabListTag.decorate("rEmOtE", displayed);
        if (!tagged.getString().equals("\uE000 [Team] Remote")
                || ((MutableComponent)tagged).siblings.get(2) != displayed)
            throw new AssertionError("Cubeon stranger must get the logo and retain the styled name");
        int cached = requests.get();
        for (int i=0;i<1000;i++) {
            if (RemoteSkins.get("Remote") != skin || !RemoteSkins.isCubeonPlayer("REMOTE"))
                throw new AssertionError("cache identity changed");
            TabListTag.decorate("Remote", displayed);
        }
        if (requests.get()!=cached) throw new AssertionError("frames repeated peer requests");
        Minecraft.getInstance().level = new net.minecraft.client.multiplayer.ClientLevel();
        RemoteSkins.context(Minecraft.getInstance().level);
        if (RemoteSkins.get("Remote") != skin || requests.get()!=cached)
            throw new AssertionError("world changes discarded completed skins");

        RemoteSkins.get("Unknown"); settled("Unknown");
        int missing = requests.get();
        for (int i=0;i<100;i++) RemoteSkins.get("Unknown");
        if (requests.get()!=missing) throw new AssertionError("missing peer was not cached");
        if (RemoteSkins.isCubeonPlayer("Unknown") || TabListTag.decorate("Unknown", displayed) != displayed)
            throw new AssertionError("non-Cubeon player received a badge");

        int defaultStart = requests.get();
        if (RemoteSkins.isCubeonPlayer("DefaultSkin")) throw new AssertionError("cold profile was confirmed");
        settled("DefaultSkin");
        if (!RemoteSkins.isCubeonPlayer("defaultskin") || RemoteSkins.get("DefaultSkin") != null
                || requests.get() != defaultStart+1 || TabListTag.decorate("DefaultSkin", displayed) == displayed)
            throw new AssertionError("cape-only Cubeon player needs a badge without downloading a skin");

        RemoteSkins.isCubeonPlayer("Broken"); settled("Broken");
        if (!RemoteSkins.isCubeonPlayer("Broken") || RemoteSkins.get("Broken") != null)
            throw new AssertionError("missing skin texture erased a confirmed Cubeon identity");

        for (String invalid : new String[]{"Mismatch", "Malformed"}) {
            RemoteSkins.isCubeonPlayer(invalid); settled(invalid);
            if (RemoteSkins.isCubeonPlayer(invalid) || TabListTag.decorate(invalid, displayed) != displayed)
                throw new AssertionError("invalid profile earned a badge: " + invalid);
            clock.addAndGet(TimeUnit.MINUTES.toNanos(2));
        }

        absent.add("/skins/defaultskin.json");
        clock.addAndGet(TimeUnit.MINUTES.toNanos(6));
        RemoteSkins.isCubeonPlayer("DefaultSkin"); settled("DefaultSkin");
        if (RemoteSkins.isCubeonPlayer("DefaultSkin") || TabListTag.decorate("DefaultSkin", displayed) != displayed)
            throw new AssertionError("removed/blocked profile kept its badge");
        RemoteSkins.context(null);
        int noWorld = requests.get();
        if (RemoteSkins.isCubeonPlayer("Remote") || RemoteSkins.isCubeonPlayer("NewPlayer"))
            throw new AssertionError("profile lookups continued after leaving the world");
        if (requests.get()!=noWorld) throw new AssertionError("menu queued network requests");
        RemoteSkins.context(Minecraft.getInstance().level);

        RemoteSkins.get("Limited"); settled("Limited");
        int limited = requests.get();
        RemoteSkins.context(new Object());
        for (int i=0;i<100;i++) RemoteSkins.get("Retry"+i);
        if (requests.get()!=limited) throw new AssertionError("Retry-After did not stop the queue");
        clock.addAndGet(TimeUnit.HOURS.toNanos(1));
        RemoteSkins.get("Recovered"); settled("Recovered");
        if (requests.get()!=limited+2 || RemoteSkins.get("Recovered")==null)
            throw new AssertionError("peer skins did not recover after cooldown");

        int floodStart = requests.get();
        for (int i=0;i<1000;i++) RemoteSkins.get("Flood"+i);
        Field cacheField = RemoteSkins.class.getDeclaredField("CACHE"); cacheField.setAccessible(true);
        for (int i=0;i<1000;i++) {
            boolean queued;
            synchronized (RemoteSkins.class) {
                queued = ((Map<?,?>)cacheField.get(null)).containsKey("flood"+i);
            }
            if (queued) settled("Flood"+i);
        }
        if (requests.get()-floodStart > 78) throw new AssertionError("distinct-name storm escaped token budget");
        System.out.println("PASS: peer skins and Tab badges identify strangers/default skins, preserve names, and stay async, bounded and recoverable");
    }
}
'''


def main() -> int:
    javac, java = find_jdk()
    if not javac:
        print("SKIP: JDK 17+ unavailable")
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        harness = root / "PeerSkinTest.java"
        harness.write_text(HARNESS, encoding="utf-8")
        sources = [
            ROOT / "mod/src/main/java/com/cubeon/client/Json.java",
            ROOT / "mod/src/main/java/com/cubeon/client/Bridge.java",
            ROOT / "mod/src/main/java/com/cubeon/client/BadgeNames.java",
            ROOT / "mod/src/main/java/com/cubeon/client/skins/RemoteSkins.java",
            ROOT / "mod/src/main/java-overlay-api-mojang/com/cubeon/client/TabListTag.java",
            ROOT / "mod/src/main/java-overlay-tab-logo-mojang/com/cubeon/client/TabLogo.java",
            harness,
        ]
        needed = ["net/minecraft/network/chat/Component.java",
                  "net/minecraft/network/chat/Style.java", "net/minecraft/network/chat/FontDescription.java",
                  "net/minecraft/network/chat/TextColor.java", "net/minecraft/ChatFormatting.java",
                  "net/minecraft/resources/Identifier.java", "net/minecraft/util/FormattedCharSequence.java",
                  "net/minecraft/client/multiplayer/PlayerInfo.java",
                  "net/minecraft/client/multiplayer/ClientLevel.java", "com/mojang/authlib/GameProfile.java"]
        stubs = {name: STUBS[name] for name in needed}
        # Reuse the compile gate's native API subset, with observable component
        # children and a stable world to exercise the actual decoration method.
        stubs["net/minecraft/network/chat/MutableComponent.java"] = r'''
            package net.minecraft.network.chat;
            public final class MutableComponent implements Component {
                private final String text;
                public final java.util.List<Component> siblings = new java.util.ArrayList<>();
                public MutableComponent(String text) { this.text = text; }
                public String getString() {
                    StringBuilder out = new StringBuilder(text);
                    for (Component child : siblings) out.append(child.getString());
                    return out.toString();
                }
                public net.minecraft.util.FormattedCharSequence getVisualOrderText() { return null; }
                public MutableComponent append(Component child) { siblings.add(child); return this; }
                public MutableComponent withStyle(Style style) { return this; }
            }
        '''
        stubs["net/minecraft/client/Minecraft.java"] = r'''
            package net.minecraft.client;
            public class Minecraft {
                private static final Minecraft INSTANCE = new Minecraft();
                public net.minecraft.client.multiplayer.ClientLevel level = new net.minecraft.client.multiplayer.ClientLevel();
                public static Minecraft getInstance() { return INSTANCE; }
            }
        '''
        for name, source in stubs.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="utf-8")
            sources.append(path)
        subprocess.run([javac, "--release", "17", "-d", tmp, *map(str, sources)], check=True)
        subprocess.run([java, "-cp", tmp, "com.cubeon.client.skins.PeerSkinTest"],
                       check=True, timeout=20)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
