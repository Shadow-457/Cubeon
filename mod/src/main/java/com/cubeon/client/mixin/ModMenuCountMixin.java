package com.cubeon.client.mixin;

import com.cubeon.client.ModFileCount;
import net.fabricmc.loader.api.FabricLoader;
import net.fabricmc.loader.api.metadata.ModOrigin;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Pseudo;
import org.spongepowered.asm.mixin.Unique;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

import java.text.NumberFormat;
import java.util.ArrayList;

/** Optional Mod Menu integration: its title/button count reflects loaded mod files. */
@Pseudo
@Mixin(targets = "com.terraformersmc.modmenu.ModMenu", remap = false)
public abstract class ModMenuCountMixin {
    @Unique private static int cubeon$fileCount = -1;
    @Inject(method = "getDisplayedModCount", at = @At("HEAD"), cancellable = true, remap = false)
    private static void cubeon$countFiles(CallbackInfoReturnable<String> ci) {
        if (cubeon$fileCount < 0) {
            var sources = new ArrayList<ModFileCount.Source>();
            for (var mod : FabricLoader.getInstance().getAllMods()) {
                var origin = mod.getOrigin();
                if (origin.getKind() == ModOrigin.Kind.PATH)
                    sources.add(new ModFileCount.Source(mod.getMetadata().getType(), "PATH", origin.getPaths()));
            }
            cubeon$fileCount = ModFileCount.count(sources);
        }
        ci.setReturnValue(NumberFormat.getIntegerInstance().format(cubeon$fileCount));
    }
}
