package com.cubeon.client.mixin;

import net.minecraft.client.Options;
import net.minecraft.client.Minecraft;
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
@Mixin(Options.class)
public abstract class GuiScaleDefaultMixin {
    @Inject(method="<init>", at=@At("HEAD"), require=1)
    private static void cubeon$migrateMenuKey(Minecraft client, File directory, CallbackInfo ci) {
        MenuKeyMigration.migrate(directory);
    }
    @ModifyConstant(method = "<init>", constant = @Constant(intValue = 0, ordinal = 1), require = 1,
            slice = @Slice(from = @At(value = "CONSTANT", args = "stringValue=options.guiScale"),
                    to = @At(value = "FIELD", target = "Lnet/minecraft/client/Options;guiScale:Lnet/minecraft/client/OptionInstance;")))
    private int cubeon$initialGuiScale(int original) { return 2; }

    // Sodium 0.9 exposes vanilla's See-Through Leaves option on 26.3.
    // Earlier versions have no such field; their own graphics options remain intact.
    @ModifyConstant(method = "<init>", constant = @Constant(intValue = 1), require = 0,
            slice = @Slice(from = @At(value = "CONSTANT", args = "stringValue=options.cutoutLeaves"),
                    to = @At(value = "FIELD", target = "Lnet/minecraft/client/Options;cutoutLeaves:Lnet/minecraft/client/OptionInstance;")))
    private int cubeon$initialSeeThroughLeaves(int original) { return 0; }
}
