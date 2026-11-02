package com.cubeon.client;

import net.minecraft.network.chat.Component;
import net.minecraft.network.chat.contents.TranslatableContents;

/** Construction-time compatibility with Sodium's pre-0.8 option objects. */
public final class ChunkDistanceOptions {
    private ChunkDistanceOptions() {}

    public static int sodiumMinimum(Object option, int original) {
        try {
            Object name = option.getClass().getMethod("getName").invoke(option);
            if (name instanceof Component text && text.getContents() instanceof TranslatableContents content) {
                String key = content.getKey();
                if ("options.renderDistance".equals(key) || "options.simulationDistance".equals(key))
                    return 1;
            }
        } catch (ReflectiveOperationException | RuntimeException ignored) {
            // Unknown Sodium layouts retain their own range.
        }
        return original;
    }
}
