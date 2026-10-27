package com.cubeon.client;

import com.cubeon.client.Bridge.Toast;

import net.fabricmc.api.ClientModInitializer;

import net.minecraft.client.MinecraftClient;
import net.minecraft.text.Text;
import net.minecraft.util.Formatting;

/**
 * Mod entrypoint: starts the launcher bridge and routes launcher notifications
 * into chat.
 *
 * <p>Yarn-mapped twin of the {@code java-overlay-api-mojang} copy: Minecraft up
 * to 1.21.x ships obfuscated and this mod builds against <b>Yarn</b> there (the
 * same mappings Cubeon Client's HUD code is written in, which is why the merged mod
 * picks Yarn for the obfuscated brackets). 26.x ships unobfuscated, so its copy
 * is written in Mojang's own names and needs no mappings at all. The two copies
 * are otherwise line-for-line the same file; only the Minecraft names differ.
 *
 * <p>The bridge starts here rather than the first time a screen opens, because
 * the notifications worth having - "Ali invited you to a world", "Dee sent you
 * a friend request" - arrive while you are playing. It polls slowly (once every
 * six seconds) until a screen is actually open, so the cost of that is a socket
 * connect to localhost.
 *
 * <p>Notifications go into the chat window - persistent, scrollable, and hard to
 * miss. The call is {@code sendMessage(Text, boolean)} with the action-bar flag
 * false, the Yarn spelling of the same entry point the server's own /msg uses;
 * it has been stable across every Minecraft version this mod ships for.
 */
public class CubeonClient implements ClientModInitializer {

    private static final Text PREFIX =
            Text.literal("[Cubeon] ").formatted(Formatting.AQUA);

    @Override
    public void onInitializeClient() {
        Bridge bridge = Bridge.get();
        bridge.setToastSink(CubeonClient::announce);
        bridge.start();
        // Cosmetics are built on Fabric API's renderer registration event. Fabric
        // API is a recommended dependency, not a required one (see
        // CubeonHudClient's guard): without it the player must lose the
        // cosmetics, never the Cubeon button or the bridge.
        try {
            com.cubeon.client.cosmetics.CosmeticsClient.register();
        } catch (Throwable missingApi) {
            // No Fabric API, no renderer event. Nothing else depends on this.
        }
    }

    /**
     * Called on the bridge's poll thread, so the actual write is handed to the
     * client thread. The GUI is not thread-safe, and a concurrent write shows up
     * as a corrupted or missing line rather than an exception.
     */
    private static void announce(Toast toast) {
        if (toast == null) {
            return;
        }
        MinecraftClient mc = MinecraftClient.getInstance();
        if (mc == null) {
            return;
        }
        try {
            mc.execute(() -> {
                // Nothing to write to on the title screen, and a notification
                // about something that happened before the player joined is
                // just noise.
                if (mc.player == null) {
                    return;
                }
                Text body = Text.literal(toast.text() == null ? "" : toast.text())
                        .formatted(toast.error() ? Formatting.RED : Formatting.WHITE);
                mc.player.sendMessage(
                        Text.empty().append(PREFIX).append(body), false);
            });
        } catch (RuntimeException ignored) {
            // The client can reject queued work while it is shutting down.
        }
    }
}
