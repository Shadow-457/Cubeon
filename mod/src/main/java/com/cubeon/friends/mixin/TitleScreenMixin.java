package com.cubeon.friends.mixin;

import com.cubeon.friends.CubeonFriendsScreen;

import net.minecraft.client.gui.components.Button;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.client.gui.screens.TitleScreen;
import net.minecraft.network.chat.Component;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/**
 * Adds the small Friends corner icon to the title / main menu too, so a Cubeon
 * player can catch up on requests and jump into a friend's world before they
 * even load a singleplayer world or join a server. Same quiet-square-with-badge
 * look and top-left dock as {@link PauseScreenMixin}.
 *
 * <p>Here there is guaranteed to be no world of the player's own to host, so the
 * screen always opens with Invite blocked - the roster, joining, requests and
 * account all still work. Same fail-soft rules as {@link PauseScreenMixin}: the
 * icon is wrapped in a catch-all, and the mixin is declared {@code required:
 * false} so an unexpected title screen is left alone rather than broken.
 */
@Mixin(TitleScreen.class)
public abstract class TitleScreenMixin extends Screen {

    private static final Logger LOGGER = LoggerFactory.getLogger("cubeon-friends");

    /** One log line per session, not one per title-screen open. */
    private static boolean cubeon$warned;

    protected TitleScreenMixin() {
        super(Component.empty());
    }

    @Inject(method = "init", at = @At("TAIL"), require = 0)
    private void cubeon$addFriendsButton(CallbackInfo ci) {
        try {
            if (this.minecraft == null) {
                return;
            }

            // No world exists here, so invites can never complete - the icon
            // opens the screen with Invite blocked; joining still works.
            Button friends = CubeonFriendsScreen.menuButton(this, false);
            friends.setX(CubeonFriendsScreen.ICON_INSET);
            friends.setY(CubeonFriendsScreen.ICON_INSET);
            this.addRenderableWidget(friends);
        } catch (Throwable ex) {
            // A broken title screen is catastrophic; a missing Friends icon is not.
            if (!cubeon$warned) {
                cubeon$warned = true;
                LOGGER.warn("Cubeon Friends: could not add the Friends icon", ex);
            }
        }
    }
}