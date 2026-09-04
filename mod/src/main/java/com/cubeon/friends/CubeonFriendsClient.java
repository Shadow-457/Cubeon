package com.cubeon.friends;

import com.cubeon.friends.Bridge.Toast;

import net.fabricmc.api.ClientModInitializer;

import net.minecraft.ChatFormatting;
import net.minecraft.client.Minecraft;
import net.minecraft.network.chat.Component;

/**
 * Mod entrypoint: starts the launcher bridge and routes launcher notifications
 * into chat.
 *
 * <p>The bridge starts here rather than the first time the Friends screen opens,
 * because the notifications worth having - "Ali invited you to a world", "Dee
 * sent you a friend request" - arrive while you are playing, not while you are
 * staring at a menu. It polls slowly (once every six seconds) until a screen is
 * actually open, so the cost of that is a socket connect to localhost.
 *
 * <p>Notifications go into the chat window - persistent, scrollable, and hard
 * to miss, unlike the overlay line above the hotbar which faded in seconds and
 * was exactly how "No Cubeon user named X" answers got missed. The call is
 * {@code LocalPlayer.displayClientMessage(Component, boolean)} with the
 * action-bar flag false, the same entry point the server's own /msg uses; it
 * has been stable across every Minecraft version Cubeon can launch, which is
 * more than can be said for {@code ChatComponent.addMessage} (private, four
 * arguments, by 26.x) or {@code SystemToast}'s factories. This mod also asks
 * for no Fabric API modules at all for the same reason - loader only - so it
 * installs on a plain Fabric profile with nothing else in the mods folder.
 */
public class CubeonFriendsClient implements ClientModInitializer {

    private static final Component PREFIX =
            Component.literal("[Cubeon] ").withStyle(ChatFormatting.AQUA);

    @Override
    public void onInitializeClient() {
        Bridge bridge = Bridge.get();
        bridge.setToastSink(CubeonFriendsClient::announce);
        bridge.start();
    }

    /**
     * Called on the bridge's poll thread, so the actual write is handed to the
     * client thread. The GUI is not thread-safe, and a concurrent write shows up
     * as a corrupted or missing line rather than an exception.
     */
    private static void announce(Toast toast) {
        Minecraft mc = Minecraft.getInstance();
        mc.execute(() -> {
            // Nothing to write to on the title screen, and a notification about
            // something that happened before the player joined is just noise.
            if (mc.player == null) {
                return;
            }
            Component body = Component.literal(toast.text())
                    .withStyle(toast.error() ? ChatFormatting.RED : ChatFormatting.WHITE);
            // Chat (persistent, scrollable), not the action bar. This method
            // is the one chat entry point present in BOTH eras the mod ships
            // for: displayClientMessage(Component, boolean) was renamed away
            // by 26.x, but sendSystemMessage(Component) kept the same shape.
            mc.player.sendSystemMessage(
                    Component.empty().append(PREFIX).append(body));
        });
    }
}
