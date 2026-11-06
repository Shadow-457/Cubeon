package com.cubeon.client.skins;

import com.cubeon.client.Bridge;
import com.cubeon.client.Json;
import java.io.ByteArrayInputStream;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Base64;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import javax.imageio.ImageIO;

/** Immutable library pages and one asynchronous action at a time. No render-thread I/O. */
public final class SkinLibrary implements AutoCloseable {
    public record Skin(String id, String name, boolean slim, String model, byte[] png, int[] pixels,
                       int width, int height, boolean hidden, byte[] texturePng) {
        static Skin read(Object value) throws Exception {
            if (!(value instanceof Map<?, ?> raw)) throw new IllegalArgumentException("Invalid skin.");
            Object encoded = raw.get("png");
            if (!(encoded instanceof String text) || text.length() > 65536) throw new IllegalArgumentException("Invalid skin image.");
            byte[] png = Base64.getDecoder().decode(text);
            var image = ImageIO.read(new ByteArrayInputStream(png));
            if (image == null || image.getWidth() != 64 || (image.getHeight() != 64 && image.getHeight() != 32))
                throw new IllegalArgumentException("Invalid skin dimensions.");
            byte[] texture = png;
            if (image.getHeight() == 32 && raw.get("texture_path") instanceof String path) {
                Path file = Path.of(path);
                if (!file.isAbsolute() || java.nio.file.Files.isSymbolicLink(file)
                        || java.nio.file.Files.size(file) > 8 * 1024 * 1024)
                    throw new IllegalArgumentException("Invalid cape source.");
                texture = java.nio.file.Files.readAllBytes(file);
                var full = ImageIO.read(new ByteArrayInputStream(texture));
                if (full == null || full.getWidth() < 64 || full.getWidth() > 1024
                        || Integer.bitCount(full.getWidth()) != 1 || full.getWidth() != full.getHeight() * 2)
                    throw new IllegalArgumentException("Invalid cape source dimensions.");
            }
            String id = String.valueOf(raw.get("id")), name = String.valueOf(raw.get("name"));
            return new Skin(id, name, Boolean.TRUE.equals(raw.get("slim")), String.valueOf(raw.get("model")),
                    png, image.getRGB(0, 0, 64, image.getHeight(), null, 0, 64),
                    64, image.getHeight(), Boolean.TRUE.equals(raw.get("hidden")), texture);
        }
    }
    public record State(List<Skin> items, Skin applied, String selected, int offset, int total,
                        int pageSize, boolean busy, String status, boolean support) {
        public Skin selectedSkin() {
            for (Skin skin : items) if (skin.id().equals(selected)) return skin;
            return applied != null && applied.id().equals(selected) ? applied : null;
        }
    }
    private final ThreadPoolExecutor worker = new ThreadPoolExecutor(1, 1, 0, TimeUnit.SECONDS,
            new ArrayBlockingQueue<>(1), task -> {
                var thread = new Thread(task, "cubeon-skin-library"); thread.setDaemon(true); return thread;
            });
    private volatile State state = new State(List.of(), null, "", 0, 0, 12, false, "", true);
    private boolean closed;
    private volatile String playerName = "Player";
    private volatile Skin playerSkin;
    private final String kind;
    public SkinLibrary() { this("skin"); }
    public SkinLibrary(String kind) { this.kind=kind; }
    public boolean capes() { return "cape".equals(kind); }
    public Skin playerSkin() { return playerSkin; }
    public String playerName() { return playerName; }
    public State state() { return state; }
    public void open() { load(0); }
    public synchronized void select(String id) {
        State s = state;
        state = new State(s.items(), s.applied(), id, s.offset(), s.total(), s.pageSize(), s.busy(), s.status(), s.support());
    }
    public void load(int offset) { run(capes()?"Loading capes…":"Loading skins…", () -> Bridge.get().skinLibrary(offset, kind), false, false); }
    public void page(int direction) {
        State s = state;
        int offset = Math.max(0, s.offset() + direction * s.pageSize());
        if (offset < s.total() || offset == 0) load(offset);
    }
    public void apply() {
        State s = state; Skin skin = s.selectedSkin();
        if (skin == null) return;
        action("apply", capes()?"Applying cape…":"Applying skin…", "", "", true);
    }
    public void model() {
        Skin skin = state.selectedSkin();
        if (capes() || skin == null || skin.id().isEmpty()) return;
        String next = switch (skin.model()) { case "auto" -> "slim"; case "slim" -> "classic"; default -> "auto"; };
        action("model", "Updating arm model…", "model", next,
                state.applied() != null && skin.id().equals(state.applied().id()));
    }
    public void delete() { action("delete", capes()?"Deleting cape…":"Deleting skin…", "", "", false); }
    public void export() {
        Skin skin = state.selectedSkin();
        if (skin == null) return;
        run(capes()?"Choose where to save the cape…":"Choose where to save the skin…", () -> {
            var dialogs = Class.forName("org.lwjgl.util.tinyfd.TinyFileDialogs");
            var pointer = Class.forName("org.lwjgl.PointerBuffer");
            var save = dialogs.getMethod("tinyfd_saveFileDialog", CharSequence.class, CharSequence.class,
                    pointer, CharSequence.class);
            Object picked = save.invoke(null, capes()?"Export Minecraft cape PNG":"Export Minecraft skin PNG", capes()?"cape.png":"skin.png", null, "PNG image");
            if (!(picked instanceof String file) || file.isBlank()) return Map.of("cancelled", true);
            Path destination = Path.of(file.endsWith(".png") ? file : file + ".png");
            java.nio.file.Files.write(destination, skin.texturePng());
            return Map.of("cancelled", true, "status", capes()?"Cape exported.":"Skin exported.");
        }, false, false);
    }
    public void lookup(String username) { if(!capes()) action("lookup", "Finding skin…", "username", username.trim(), false); }
    public void importPath(Path file) { action("import", capes()?"Importing cape…":"Importing skin…", "path", file.toAbsolutePath().toString(), false); }
    public void chooseFile() {
        run(capes()?"Choose a cape image…":"Choose a skin PNG…", () -> {
            // tinyfd is part of Minecraft's LWJGL distribution. Reflection keeps
            // the shared UI independent of Minecraft's changing native versions.
            var dialogs = Class.forName("org.lwjgl.util.tinyfd.TinyFileDialogs");
            var pointer = Class.forName("org.lwjgl.PointerBuffer");
            var open = dialogs.getMethod("tinyfd_openFileDialog", CharSequence.class, CharSequence.class,
                    pointer, CharSequence.class, boolean.class);
            Object picked = open.invoke(null, capes()?"Import Minecraft cape image":"Import Minecraft skin PNG", "", null, capes()?"Cape image":"PNG skin", false);
            if (!(picked instanceof String file) || file.isBlank()) return Map.of("cancelled", true);
            return Bridge.get().skinAction(body("import", "path", file));
        }, false, true);
    }
    private void action(String action, String label, String key, String value, boolean live) {
        String body = body(action, key, value);
        run(label, () -> Bridge.get().skinAction(body), live, true);
    }
    private String body(String action, String key, String value) {
        State s = state;
        return "{\"action\":" + Json.quote(action) + ",\"id\":" + Json.quote(s.selected())
                + ",\"kind\":" + Json.quote(kind)
                + ",\"offset\":" + s.offset() + ",\"game_dir\":"
                + Json.quote(Path.of("").toAbsolutePath().normalize().toString())
                + (key.isEmpty() ? "" : "," + Json.quote(key) + ":" + Json.quote(value)) + "}";
    }
    private interface Request { Map<String, Object> get() throws Exception; }
    private synchronized void run(String label, Request request, boolean live, boolean selectResult) {
        if (closed || state.busy()) return;
        State before = state;
        state = new State(before.items(), before.applied(), before.selected(), before.offset(), before.total(),
                before.pageSize(), true, label, before.support());
        worker.execute(() -> {
            try {
                Map<String, Object> reply = request.get();
                if (Boolean.TRUE.equals(reply.get("cancelled"))) { finish(before, Json.str(reply, "status", "")); return; }
                if (!Json.bool(reply, "ok", false)) {
                    finish(before, Json.str(reply, "error", "Couldn't load skins. Try again.")); return;
                }
                var items = new ArrayList<Skin>();
                if (reply.get("items") instanceof List<?> list)
                    for (Object item : list) { if (items.size() == (capes()?14:13)) break; items.add(Skin.read(item)); }
                Skin applied = Skin.read(reply.get("applied"));
                playerName = Json.str(reply, "username", "Player");
                if(reply.get("player_skin") != null) playerSkin = Skin.read(reply.get("player_skin"));
                if (live) { if(capes()) LiveCape.apply(applied); else LiveSkin.apply(applied); }
                String selected = selectResult ? Json.str(reply, "selected", applied.id()) : applied.id();
                String status = live ? (capes()?"Cape applied.":"Skin applied.") : selectResult ? (capes()?"Ready. Choose Confirm to wear this cape.":"Ready. Choose Confirm to use this skin.") : "";
                state = new State(List.copyOf(items), applied, selected, (int) Json.num(reply, "offset"),
                        (int) Json.num(reply, "total"), Math.max(1, (int) Json.num(reply, "page_size")), false,
                        status, Json.bool(reply, "skin_support", true));
            } catch (Throwable failure) {
                finish(before, capes()?"Couldn't open the cape library. Try again or import an image.":"Couldn't open the skin library. Try again or drop a PNG onto this screen.");
            }
        });
    }
    private void finish(State before, String status) {
        state = new State(before.items(), before.applied(), before.selected(), before.offset(), before.total(),
                before.pageSize(), false, status, before.support());
    }
    @Override public synchronized void close() { closed = true; worker.shutdown(); }
}
