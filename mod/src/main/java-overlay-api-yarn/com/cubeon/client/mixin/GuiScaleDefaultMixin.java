package com.cubeon.client.mixin;

import net.minecraft.client.option.GameOptions;
import net.minecraft.client.MinecraftClient;
import java.io.File;
import com.cubeon.client.MenuKeyMigration;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Constant;
import org.spongepowered.asm.mixin.injection.ModifyConstant;
import org.spongepowered.asm.mixin.injection.Slice;

/** Set the option's initial value, before vanilla loads the player's saved value. */
@Mixin(GameOptions.class)
public abstract class GuiScaleDefaultMixin {
    @Inject(method="<init>", at=@At("HEAD"), require=1)
    private static void cubeon$migrateMenuKey(MinecraftClient client, File directory, CallbackInfo ci) {
        MenuKeyMigration.migrate(directory);
    }
    @ModifyConstant(method = "<init>", constant = @Constant(intValue = 0, ordinal = 1), require = 1,
            slice = @Slice(from = @At(value = "CONSTANT", args = "stringValue=options.guiScale"),
                    to = @At(value = "FIELD", target = "Lnet/minecraft/client/option/GameOptions;guiScale:Lnet/minecraft/client/option/SimpleOption;")))
    private int cubeon$initialGuiScale(int original) { return 2; }
}
