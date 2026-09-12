package com.cubeon.client.mixin;

import com.cubeon.client.Nametag;

import net.minecraft.network.chat.Component;
import net.minecraft.world.entity.player.Player;

import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/**
 * Puts the Cubeon badge in front of Cubeon players' names: {@code [#]Shadow}.
 *
 * <p>Why {@code Player.getDisplayName()} and not the nametag renderer: the
 * renderer is the single most-reshaped piece of client code between the two eras
 * this mod ships for - {@code renderNameTag} took an entity and a
 * {@code PoseStack} in 1.20, and by 26.x the whole entity render path goes
 * through extracted render-state objects. {@code getDisplayName()} is what BOTH
 * of them read the name out of, and it is declared right here on {@code Player}
 * with the same {@code ()Component} shape in 1.20.1 and 26.1.2 (verified against
 * the shipped jar). One injection, both eras, no per-version renderer code.
 *
 * <p>It also means the badge follows the name wherever the client draws it from
 * this method, which is the nametag above the head. The tab list builds its own
 * component from the profile and is deliberately untouched - a badge on every row
 * of the player list would be noise, not identity.
 *
 * <p>Fail-soft like the rest of the mod: {@code require = 0} so a future version
 * that moves the method loses the badge instead of the game, and the body is
 * wrapped - {@code getDisplayName} is called once per visible player per frame,
 * so an exception here would be a crash-per-frame rather than a one-off.
 */
@Mixin(Player.class)
public abstract class PlayerNameMixin {

    @Inject(method = "getDisplayName", at = @At("RETURN"), cancellable = true, require = 0)
    private void cubeon$badgeName(CallbackInfoReturnable<Component> cir) {
        try {
            Object self = this;
            Component badged = Nametag.decorate(
                    self, ((Player) self).getName().getString(), cir.getReturnValue());
            if (badged != null) {
                cir.setReturnValue(badged);
            }
        } catch (Throwable ignored) {
            // A missing badge is invisible; a throwing nametag is the game.
        }
    }
}
