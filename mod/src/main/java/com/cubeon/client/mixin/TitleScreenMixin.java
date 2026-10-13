package com.cubeon.client.mixin;

import com.cubeon.client.CubeonClientScreen;

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
 * Adds the small chat corner icon to the title / main menu too, so a Cubeon
 * player can catch up on conversations before they even load a world or join a
 * server. Same top-left dock as {@link PauseScreenMixin}.
 *
 * <p>Same fail-soft rules as {@link PauseScreenMixin}: the icon is wrapped in a
 * catch-all, and the mixin is declared {@code required: false} so an unexpected
 * title screen is left alone rather than broken.
 */
@Mixin(TitleScreen.class)
public abstract class TitleScreenMixin extends Screen {

    private static final Logger LOGGER = LoggerFactory.getLogger("cubeon-client");

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

            Button friends = CubeonClientScreen.menuButton(this);
            friends.setX(CubeonClientScreen.ICON_INSET);
            friends.setY(CubeonClientScreen.ICON_INSET);
            this.addRenderableWidget(friends);
        } catch (Throwable ex) {
            // A broken title screen is catastrophic; a missing chat icon is not.
            if (!cubeon$warned) {
                cubeon$warned = true;
                LOGGER.warn("Cubeon Client: could not add the chat icon", ex);
            }
        }
    }
}