package com.cubeon.client.mixin;

import com.cubeon.client.CubeonClientScreen;

import net.minecraft.client.gui.components.Button;
import net.minecraft.client.gui.screens.PauseScreen;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.network.chat.Component;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/**
 * Adds a small Friends corner icon to Minecraft's own game menu
 * (Escape / PauseScreen), docked at the top-left rather than joining the menu's
 * button column. The icon is a quiet square until invites or friend requests
 * are waiting, when it shows their count as a badge.
 *
 * <p>Deliberately contains NO {@code @Shadow} members. A shadow has to belong to
 * the target class itself, and everything used here - {@code addRenderableWidget()},
 * {@code minecraft} - is declared on the {@code Screen} superclass. Inheriting
 * them is what makes this mixin portable: it touches only long-stable public
 * Screen API instead of fields that get renamed or moved between Minecraft
 * versions.
 *
 * <p>Invites are only offered in a singleplayer world: the invite flow ends with
 * "open your world to LAN", which only makes sense in a world the player hosts.
 * From a remote server's pause menu the icon still shows, but the Invite action
 * on the Friends screen is greyed out - joining and requests still work.
 *
 * <h2>Fail-soft on purpose</h2>
 *
 * The pause menu is not this mod's feature - it is Minecraft's - so getting it
 * wrong must never cost the player their game. Three things guarantee that:
 * {@code require = 0} plus {@code required: false} in the mixin config mean a
 * version whose {@code init} does not match is logged and skipped rather than
 * crashed on; the body is wrapped in a catch-all, because an exception thrown out
 * of {@code PauseScreen.init} takes the whole client down mid-game; and the icon
 * is only added once the screen is known to be a real in-game pause menu (it also
 * backs the "saving world" overlay, where {@code minecraft.player} is null).
 */
@Mixin(PauseScreen.class)
public abstract class PauseScreenMixin extends Screen {

    private static final Logger LOGGER = LoggerFactory.getLogger("cubeon-client");

    /** One log line per session, not one per pause-menu open. */
    private static boolean cubeon$warned;

    protected PauseScreenMixin() {
        super(Component.empty());
    }

    @Inject(method = "init", at = @At("TAIL"), require = 0)
    private void cubeon$addFriendsButton(CallbackInfo ci) {
        try {
            if (this.minecraft == null || this.minecraft.player == null) {
                return;   // the pause screen also backs the "saving world" screen
            }

            // Inviting only makes sense in a world the player hosts (the flow ends
            // in "open your world to LAN"). A singleplayer world is such a world;
            // a remote server's pause menu is not - there the icon still opens
            // the screen, but Invite is blocked there.
            boolean canInvite = this.minecraft.hasSingleplayerServer();

            Button friends = CubeonClientScreen.menuButton(this, canInvite);
            friends.setX(CubeonClientScreen.ICON_INSET);
            friends.setY(CubeonClientScreen.ICON_INSET);
            this.addRenderableWidget(friends);

            // The mod menu sits to the right of the Friends icon rather than in
            // the menu's button column: a full-width "Cubeon" button in
            // Minecraft's own pause menu is the thing this whole screen docks
            // out of the way of. It only exists in a live world - a module is
            // meaningless on the title screen, which never opens one.
            Button mods = Button
                    .builder(Component.literal("Mods"), button ->
                            this.minecraft.setScreen(
                                    new com.cubeon.client.ModuleMenuScreen(this)))
                    .bounds(CubeonClientScreen.ICON_INSET
                                    + CubeonClientScreen.ICON_W + 2,
                            CubeonClientScreen.ICON_INSET, 34, CubeonClientScreen.ICON_H)
                    .build();
            this.addRenderableWidget(mods);
        } catch (Throwable ex) {
            // Whatever went wrong, the player still gets a working pause menu.
            if (!cubeon$warned) {
                cubeon$warned = true;
                LOGGER.warn("Cubeon Client: could not add the Friends icon", ex);
            }
        }
    }
}
