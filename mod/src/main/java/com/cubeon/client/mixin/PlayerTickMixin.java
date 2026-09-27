package com.cubeon.client.mixin;

import com.cubeon.client.modules.Modules;

import net.minecraft.client.Minecraft;
import net.minecraft.client.player.LocalPlayer;

import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/**
 * Drives the modules that need a per-tick hook (auto-sprint today).
 *
 * <p>This mod deliberately depends on no Fabric API modules - only
 * fabric-loader - so there is no {@code ClientTickEvents} to hang this on, and
 * {@code LocalPlayer.tick()} is the stable equivalent. Verified with javap to
 * have the same shape in 1.20.1 and 26.1.2, which is the whole reason this is
 * a shared file rather than a per-bracket one.
 *
 * <p>Injected at TAIL so the game's own movement has already run this tick -
 * a module that reads the player's input before it updates would act on last
 * tick's values.
 *
 * <p>Fail-soft like every other mixin here: {@code require = 0} so a version
 * that reshapes the method loses the modules instead of the game, and the body
 * is wrapped because an exception out of a player tick is a crash, not a
 * one-off.
 */
@Mixin(LocalPlayer.class)
public abstract class PlayerTickMixin {

    @Inject(method = "tick", at = @At("TAIL"), require = 0)
    private void cubeon$runModules(CallbackInfo ci) {
        try {
            Minecraft mc = Minecraft.getInstance();
            // The keybind, checked BEFORE the modules so a keypress is not
            // eaten by whatever a module does this tick. Only with no screen
            // open: that is what stops K being intercepted while the player is
            // typing, and it also stops an open menu being reopened by its own
            // key.
            if (mc.screen == null
                    && com.cubeon.client.keys.MenuKey.justPressed()) {
                mc.setScreen(new com.cubeon.client.ModuleMenuScreen(null));
            }
            Modules.get().tick(mc);
        } catch (Throwable ignored) {
            // A module must never be able to break the player's movement.
        }
    }
}
