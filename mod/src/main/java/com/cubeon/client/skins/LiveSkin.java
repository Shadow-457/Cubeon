package com.cubeon.client.skins;

import com.cubeon.client.Json;

import java.util.Arrays;
import java.util.Map;

/** The selected local skin, consumed by the native adapter on the game thread. */
public final class LiveSkin {
    public record Applied(byte[] png, boolean slim, long revision) { }
    private static volatile Applied applied;
    private static long revision;
    private static boolean managed;

    private LiveSkin() { }

    public static Applied get() { return applied; }

    public static synchronized void apply(SkinLibrary.Skin skin) {
        managed = false;
        update(skin);
    }

    /** Called off-thread through the existing authenticated cape poll. */
    public static synchronized void accept(Map<String, Object> response) {
        if (!Json.bool(response, "ok", false) || !(response.get("skin") instanceof Map<?, ?> skin)) return;
        String mode = Json.str(skin, "mode", "");
        switch (mode) {
            case "disabled" -> applied = null;
            case "unmanaged" -> {
                if (managed) applied = null;
            }
            case "managed" -> {
                Object texture = skin.get("applied");
                if (texture == null) {
                    applied = null;
                    return;
                }
                try {
                    // Consecutive polls can contain the same image. Skip
                    // decoding and preserve the existing GPU texture revision.
                    String hash = Json.str(texture, "hash", "");
                    if (hash.isEmpty()) return;
                    boolean slim = Json.bool(texture, "slim", false);
                    if (applied == null || !hash.equals(polledHash) || slim != applied.slim() || !managed) {
                        update(SkinLibrary.Skin.read(texture));
                        polledHash = hash;
                    }
                    managed = true;
                } catch (Exception invalid) {
                    // Keep the last good selection and retry on the next poll.
                }
            }
            default -> { } // Transient error or a launcher without live skin state.
        }
    }

    private static String polledHash = "";

    private static void update(SkinLibrary.Skin skin) {
        if (applied != null && applied.slim() == skin.slim() && Arrays.equals(applied.png(), skin.png())) return;
        applied = new Applied(skin.png(), skin.slim(), ++revision);
    }
}
