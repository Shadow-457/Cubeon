package com.cubeon.client.hud.screen;

import com.cubeon.client.ui.SkinMenu;
import net.minecraft.world.entity.player.PlayerModelPart;
import net.minecraft.client.Minecraft;

/** Version-specific native skin options; keep cape visibility unchanged. */
public final class SkinNative implements SkinMenu.Layers {
    private final Minecraft client=Minecraft.getInstance();
    private static final PlayerModelPart[] PARTS={PlayerModelPart.HAT,PlayerModelPart.JACKET,
            PlayerModelPart.RIGHT_SLEEVE,PlayerModelPart.LEFT_SLEEVE,
            PlayerModelPart.RIGHT_PANTS_LEG,PlayerModelPart.LEFT_PANTS_LEG};
    public int mask() {
        int value=0;
        for(int i=0;i<PARTS.length;i++) if(client.options.isModelPartEnabled(PARTS[i])) value|=1<<i;
        if(client.options.isModelPartEnabled(PlayerModelPart.CAPE)) value|=64;
        return value;
    }
    public void set(int value) {
        for(int i=0;i<PARTS.length;i++) client.options.setModelPart(PARTS[i],(value&(1<<i))!=0);
        client.options.setModelPart(PlayerModelPart.CAPE,(value&64)!=0);
        client.options.save();
    }
}
