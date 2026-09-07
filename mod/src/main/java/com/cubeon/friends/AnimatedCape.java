package com.cubeon.friends;

import java.lang.reflect.Constructor;
import java.lang.reflect.Method;
import java.util.Base64;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;

/**
 * Animated capes, self-only. The launcher stores the frames; this class swaps
 * them into the texture Minecraft is already rendering for OUR cape.
 *
 * <h2>The contract this relies on</h2>
 *
 * Cubeon's cape reaches the game through CustomSkinLoader's LocalSkin source:
 * the launcher writes {@code CustomSkinLoader/LocalSkin/capes/<USERNAME>.png}
 * and CSL registers it as the player's cape. CSL's fake-URL scheme for a local
 * file ({@code (LOCAL)LocalSkin/capes/<USERNAME>.png}) hashes to the file's
 * base name, and Minecraft's SkinManager registers cape textures under
 * {@code minecraft:capes/<hash>} - so the cape texture for user "Alex" lands
 * at the Identifier {@code minecraft:capes/Alex}. Predictable without touching
 * CSL internals.
 *
 * <h2>How the animation works</h2>
 *
 * A single daemon thread cycles frames at the configured fps. Every tick it
 * hands the GPU work to Minecraft's render thread via {@code execute(...)}
 * (public on Minecraft's event-loop superclass in every version we ship):
 * {@code setPixels(frame)} then {@code upload()} on a {@code DynamicTexture}
 * we registered over the static one. One 64x32..512x256 texture upload per
 * frame is a rounding error next to what a single chat line costs, and it
 * happens for exactly ONE cape: ours.
 *
 * <h2>Why other players never pay anything</h2>
 *
 * Other players' capes are textures under ids derived from THEIR usernames
 * (or content hashes, for network-loaded ones) on THEIR machines - this code
 * never touches those. Nobody else downloads the frames: they are read from
 * the launcher's local HTTP API bound to 127.0.0.1, which only serves
 * processes on this machine. To everyone else the cape is exactly what it
 * always was: the static PNG in the profile.
 *
 * <h2>Why everything here is reflection</h2>
 *
 * One jar spans three Minecraft eras (1.20.1, 1.21.x, 26.x) that rename the
 * same APIs between them:
 *
 * <table>
 *   <tr><th></th><th>1.20.1</th><th>1.21.x</th><th>26.x</th></tr>
 *   <tr><td>Identifier class</td><td>class_2960</td><td>class_2960</td>
 *       <td>net.minecraft.resources.Identifier</td></tr>
 *   <tr><td>Identifier make</td><td>ctor(ns, path)</td>
 *       <td>method_60655(ns, path)</td><td>withDefaultNamespace(path)</td></tr>
 *   <tr><td>TextureManager.register</td><td colspan="2">method_4616</td>
 *       <td>register</td></tr>
 *   <tr><td>DynamicTexture.upload</td><td colspan="2">method_4524</td>
 *       <td>upload</td></tr>
 * </table>
 *
 * Intermediary ids are stable within an era by design, and 26.x ships plain
 * names, so each lookup resolves on the first or second try and is cached for
 * the worker's lifetime. Every miss degrades to "cape stays static", never to
 * a crash - the same failure posture as the rest of this mod.
 *
 * <p>This class contains NO compile-time Minecraft imports (same discipline
 * as {@link Bridge}), so it compiles against a bare JDK in both brackets and
 * keeps the mod's zero-fabric-api-modules property.
 */
final class AnimatedCape {

    /** Cap shared with the launcher: the mod refuses more, whatever the API says. */
    private static final int MAX_FRAMES = 16;
    /** Hard fps ceiling: capes are cloth, not strobes; protects photosensitive players too. */
    private static final int MAX_FPS = 10;

    /** Where the animation happens. Created lazily, exits when frames vanish. */
    private static volatile Thread worker;
    /** The current frame set + fps, swapped atomically by refresh(). */
    private static volatile Plan plan;

    private AnimatedCape() {
    }

    /**
     * One refresh of the launcher's answer, called from the bridge poll
     * thread (never the render thread). A null/empty answer stops the
     * animation; a changed version swaps the frame set in place.
     */
    static void refresh(Bridge bridge) {
        try {
            Bridge.CapeFrames cf = bridge.fetchCapeFrames();
            if (cf == null || cf.frames().isEmpty()) {
                plan = null; // worker exits on its next tick
                return;
            }
            Plan old = plan;
            if (old != null && old.version == cf.version()) {
                return; // unchanged since last time; keep animating
            }
            plan = new Plan(cf.frames(), cf.fps());
            if (worker == null || !worker.isAlive()) {
                Thread t = new Thread(AnimatedCape::run, "cubeon-animated-cape");
                t.setDaemon(true);
                worker = t;
                t.start();
            }
        } catch (RuntimeException ex) {
            // Launcher down, endpoint gone, JSON weird: "no animated cape".
            plan = null;
        }
    }

    private static int clampFps(int fps) {
        if (fps <= 0) return 2;
        return Math.min(fps, MAX_FPS);
    }

    private static void run() {
        Glue glue = null;
        long frame = 0;
        while (plan != null) {
            Plan p = plan;
            if (p == null) break;
            try {
                if (glue == null) {
                    glue = Glue.create();
                    if (glue == null) return; // undrivable Minecraft: stay static
                }
                if (p.name.isEmpty()) {
                    // Minecraft wasn't up when the plan was built; try again.
                    Plan retry = new Plan(p.rawFrames, p.fps, p.version);
                    if (retry.name.isEmpty()) return;
                    p = retry;
                    plan = p;
                }
                glue.render(p.name, p.frames.get((int) (frame % p.frames.size())));
                frame++;
                Thread.sleep(1000L / p.fps);
            } catch (InterruptedException ie) {
                Thread.currentThread().interrupt();
                return;
            } catch (Exception ex) {
                // One bad frame or a lost race with a resource reload: skip a
                // beat rather than die - the next tick re-tries.
                try {
                    Thread.sleep(500L);
                } catch (InterruptedException ie2) {
                    Thread.currentThread().interrupt();
                    return;
                }
            }
        }
        worker = null;
    }

    /** Decoded frames + fps + the in-game name the cape id is derived from. */
    private static final class Plan {
        final List<String> rawFrames;   // base64, as the launcher sent them
        final List<byte[]> frames;      // decoded PNG bytes
        final int fps;
        final String name;
        final int version;

        Plan(List<String> base64Frames, int fps) {
            this(base64Frames, fps, -1);
        }

        Plan(List<String> base64Frames, int fps, int version) {
            this.rawFrames = base64Frames;
            this.frames = new CopyOnWriteArrayList<>();
            int n = Math.min(base64Frames.size(), MAX_FRAMES);
            for (int i = 0; i < n; i++) {
                try {
                    this.frames.add(Base64.getDecoder().decode(base64Frames.get(i)));
                } catch (IllegalArgumentException badB64) {
                    break; // truncated JSON beats a half-broken animation
                }
            }
            this.fps = clampFps(fps);
            this.name = Glue.userName();
            this.version = version;
        }
    }

    /**
     * All the Minecraft-touching reflection in one place. {@link #create()}
     * resolves every {@link Method}/{@link Constructor} up front so the
     * per-frame path does zero lookup work.
     */
    private static final class Glue {
        private final Object mc;
        private final Method execute;
        private final Method textureManager;
        private final Method register;
        private final Method getTexture;
        private final Method makeIdentifier;
        private final Class<?> dynamicTextureClass;
        private final Method setPixels;
        private final Method upload;
        private final Method imageRead;
        private final Constructor<?> textureCtorSupplier;
        private final Constructor<?> textureCtorPlain;

        // Mutable slot state, only ever touched on the render thread (inside
        // the execute() runnable), so plain fields are enough.
        private Object texture;
        private String boundName = "";
        private int boundWidth = -1;
        private int boundHeight = -1;

        private Glue(Object mc, Method execute, Method textureManager, Method register,
                     Method getTexture, Method makeIdentifier, Class<?> dynamicTextureClass,
                     Method setPixels, Method upload, Method imageRead,
                     Constructor<?> textureCtorSupplier, Constructor<?> textureCtorPlain) {
            this.mc = mc;
            this.execute = execute;
            this.textureManager = textureManager;
            this.register = register;
            this.getTexture = getTexture;
            this.makeIdentifier = makeIdentifier;
            this.dynamicTextureClass = dynamicTextureClass;
            this.setPixels = setPixels;
            this.upload = upload;
            this.imageRead = imageRead;
            this.textureCtorSupplier = textureCtorSupplier;
            this.textureCtorPlain = textureCtorPlain;
        }

        /** Resolves the era-specific surface; null if any piece is missing. */
        static Glue create() {
            try {
                Class<?> mcClass = firstClass("net.minecraft.client.Minecraft",
                                              "net.minecraft.class_310");
                if (mcClass == null) return null;
                Object mc = invokeStatic(mcClass, "getInstance", "method_1551");
                if (mc == null) return null;
                Method execute = firstMethod(mcClass, "execute");
                Method textureManager = firstMethod(mcClass, "getTextureManager", "method_1531");
                if (execute == null || textureManager == null) return null;

                Class<?> idClass = firstClass("net.minecraft.resources.Identifier",
                                              "net.minecraft.class_2960");
                if (idClass == null) return null;
                // 26.x: withDefaultNamespace(path); 1.21.x: method_60655 == of(ns, path);
                // 1.20.1: public ctor(ns, path) - handled via makeFromParts below.
                Method makeId = firstStatic(idClass, new Class<?>[]{String.class},
                                             "withDefaultNamespace", "method_12829");
                boolean needsNamespace = true;
                if (makeId == null) {
                    makeId = firstStatic(idClass, new Class<?>[]{String.class, String.class},
                                         "of", "method_60655");
                    needsNamespace = false;
                }

                Class<?> texMgrClass = textureManager.getReturnType();
                Method register = firstMethod(texMgrClass, "register", "method_4616");
                Method getTexture = firstMethod(texMgrClass, "getTexture", "method_4619");

                Class<?> dynClass = firstClass(
                        "net.minecraft.client.renderer.texture.DynamicTexture",
                        "net.minecraft.class_1043");
                Class<?> imageClass = firstClass("com.mojang.blaze3d.platform.NativeImage",
                                                 "net.minecraft.class_1011");
                if (dynClass == null || imageClass == null) return null;
                Method setPixels = firstMethodByParams(dynClass, imageClass,
                                                        "setPixels", "method_4526");
                Method upload = firstMethod(dynClass, "upload", "method_4524");
                Method imageRead = firstStatic(imageClass, new Class<?>[]{byte[].class},
                                               "read", "method_49277");

                Constructor<?> ctorSupplier = null;
                Constructor<?> ctorPlain = null;
                for (Constructor<?> c : dynClass.getConstructors()) {
                    Class<?>[] p = c.getParameterTypes();
                    if (p.length == 1 && p[0] == imageClass) ctorPlain = c;
                    if (p.length == 2 && java.util.function.Supplier.class.isAssignableFrom(p[0])
                            && p[1] == imageClass) ctorSupplier = c;
                }

                if (register == null || getTexture == null || setPixels == null
                        || upload == null || imageRead == null
                        || (ctorSupplier == null && ctorPlain == null)
                        || (makeId == null && needsNamespace && ctorPlain == null
                            && !hasTwoArgCtor(idClass))) {
                    return null;
                }
                return new Glue(mc, execute, textureManager, register, getTexture, makeId,
                                dynClass, setPixels, upload, imageRead, ctorSupplier, ctorPlain);
            } catch (RuntimeException ex) {
                return null;
            }
        }

        /** The local player's name, spelled the way CSL looked it up. */
        static String userName() {
            try {
                Class<?> mcClass = firstClass("net.minecraft.client.Minecraft",
                                              "net.minecraft.class_310");
                if (mcClass == null) return "";
                Object mc = invokeStatic(mcClass, "getInstance", "method_1551");
                if (mc == null) return "";
                Object user = firstInvoke(mc, "getUser", "method_1548");
                if (user == null) return "";
                Object name = firstInvoke(user, "getName", "method_1674");
                return name == null ? "" : String.valueOf(name);
            } catch (RuntimeException ex) {
                return "";
            }
        }

        /** One frame: decode, take over the texture slot if needed, upload. */
        void render(String username, byte[] png) throws Exception {
            final Object image = imageRead.invoke(null, (Object) png);
            final int fw = (Integer) firstInvoke(image, "getWidth", "method_105");
            final int fh = (Integer) firstInvoke(image, "getHeight", "method_104");
            final Object mcRef = mc;
            execute.invoke(mcRef, (Runnable) () -> {
                try {
                    Object tm = textureManager.invoke(mcRef);
                    Object id = makeIdentifier != null
                            ? (makeIdentifier.getParameterCount() == 1
                               ? makeIdentifier.invoke(null, (Object) ("capes/" + username))
                               : makeIdentifier.invoke(null, "minecraft",
                                                       (Object) ("capes/" + username)))
                            : null;
                    if (id == null) {
                        // 1.20.1: construct through the two-arg ctor.
                        Class<?> idClass = firstClass("net.minecraft.resources.Identifier",
                                                      "net.minecraft.class_2960");
                        id = idClass.getConstructor(String.class, String.class)
                                    .newInstance("minecraft", "capes/" + username);
                    }
                    Object current = getTexture.invoke(tm, id);
                    boolean mine = texture != null && current == texture;
                    if (!mine || boundWidth != fw || boundHeight != fh
                            || !username.equals(boundName)) {
                        // (Re)take the slot: our texture object replaces the
                        // static binding. The old binding is simply dropped
                        // from the map; we never close a texture we don't own
                        // (it may be shared elsewhere by the game).
                        if (texture != null) {
                            try {
                                dynamicTextureClass.getMethod("close").invoke(texture);
                            } catch (ReflectiveOperationException ignored) {
                            }
                        }
                        if (textureCtorSupplier != null) {
                            texture = textureCtorSupplier.newInstance(
                                    (java.util.function.Supplier<String>) () -> "cubeon-cape",
                                    image);
                        } else {
                            texture = textureCtorPlain.newInstance(image);
                        }
                        register.invoke(tm, id, texture);
                        boundName = username;
                        boundWidth = fw;
                        boundHeight = fh;
                        return; // the ctor already carries this frame's pixels
                    }
                    setPixels.invoke(texture, image);
                    upload.invoke(texture);
                } catch (Exception ignored) {
                    // Any miss just means this frame is skipped.
                }
            });
        }

        // ------------------------------------------------ reflection helpers

        private static boolean hasTwoArgCtor(Class<?> c) {
            try {
                c.getConstructor(String.class, String.class);
                return true;
            } catch (NoSuchMethodException ex) {
                return false;
            }
        }

        private static Class<?> firstClass(String... names) {
            for (String n : names) {
                try {
                    return Class.forName(n);
                } catch (ClassNotFoundException ignored) {
                }
            }
            return null;
        }

        private static Object firstInvoke(Object target, String... names) {
            for (Method m : target.getClass().getMethods()) {
                for (String n : names) {
                    if (m.getName().equals(n) && m.getParameterCount() == 0) {
                        try {
                            return m.invoke(target);
                        } catch (ReflectiveOperationException ignored) {
                        }
                    }
                }
            }
            return null;
        }

        private static Method firstMethod(Class<?> c, String... names) {
            // Prefer a 1-arg Runnable-shaped overload: several event-loop
            // methods share a plain name ("execute" vs "executeIfPossible"
            // vs bridge methods), and we always call it with a Runnable.
            Method fallback = null;
            for (Method m : c.getMethods()) {
                for (String n : names) {
                    if (m.getName().equals(n)) {
                        m.setAccessible(true);
                        Class<?>[] p = m.getParameterTypes();
                        if (p.length == 1 && Runnable.class.isAssignableFrom(p[0])) {
                            return m;
                        }
                        if (fallback == null && p.length == 1) {
                            fallback = m;
                        }
                    }
                }
            }
            return fallback;
        }

        /** A method taking exactly one argument of the given type. */
        private static Method firstMethodByParams(Class<?> c, Class<?> param, String... names) {
            for (Method m : c.getMethods()) {
                for (String n : names) {
                    if (m.getName().equals(n) && m.getParameterCount() == 1
                            && m.getParameterTypes()[0] == param) {
                        m.setAccessible(true);
                        return m;
                    }
                }
            }
            return null;
        }

        private static Method firstStatic(Class<?> c, Class<?>[] params, String... names) {
            outer:
            for (String n : names) {
                for (Method m : c.getMethods()) {
                    if (m.getName().equals(n)
                            && java.lang.reflect.Modifier.isStatic(m.getModifiers())
                            && m.getParameterCount() == params.length) {
                        for (int i = 0; i < params.length; i++) {
                            if (!params[i].isAssignableFrom(m.getParameterTypes()[i])) {
                                continue outer;
                            }
                        }
                        m.setAccessible(true);
                        return m;
                    }
                }
            }
            return null;
        }

        /** A zero-arg static lookup for getInstance(): name candidates only. */
        private static Object invokeStatic(Class<?> c, String... names) {
            for (Method m : c.getMethods()) {
                if (!java.lang.reflect.Modifier.isStatic(m.getModifiers())
                        || m.getParameterCount() != 0) {
                    continue;
                }
                for (String n : names) {
                    if (m.getName().equals(n)) {
                        try {
                            return m.invoke(null);
                        } catch (ReflectiveOperationException ignored) {
                        }
                    }
                }
            }
            return null;
        }
    }
}
