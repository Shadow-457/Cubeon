package com.cubeon.client.hud.screen;

import com.cubeon.client.ui.SkinMenu;
import net.minecraft.entity.player.PlayerModelPart;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.gui.DrawContext;
import net.minecraft.client.gui.screen.Screen;
import net.minecraft.text.Text;

/** Version-specific native skin options; keep cape visibility unchanged. */
public final class SkinNative extends Screen implements SkinMenu.Layers {
    public SkinNative() { super(Text.empty()); this.client=MinecraftClient.getInstance(); }
    private static final PlayerModelPart[] PARTS={PlayerModelPart.HAT,PlayerModelPart.JACKET,
            PlayerModelPart.RIGHT_SLEEVE,PlayerModelPart.LEFT_SLEEVE,
            PlayerModelPart.RIGHT_PANTS_LEG,PlayerModelPart.LEFT_PANTS_LEG};
    public int mask() {
        int value=0;
        for(int i=0;i<PARTS.length;i++) if(client.options.isPlayerModelPartEnabled(PARTS[i])) value|=1<<i;
        if(client.options.isPlayerModelPartEnabled(PlayerModelPart.CAPE)) value|=64;
        return value;
    }
    public void set(int value) {
        for(int i=0;i<PARTS.length;i++) client.options.setPlayerModelPart(PARTS[i],(value&(1<<i))!=0);
        client.options.setPlayerModelPart(PlayerModelPart.CAPE,(value&64)!=0);
        client.options.write();
    }
    public void draw(DrawContext context,int w,int h,float delta) {
        this.width=w; this.height=h;
        if(client.world==null) renderPanoramaBackground(context,delta);
        applyBlur(context);
        context.fill(0,0,w,h,0x9309090C);
    }
    public void frost(DrawContext context,int w,int h,float delta) {
        this.width=w; this.height=h;
        if(client.world==null) renderPanoramaBackground(context,delta);
        applyBlur(context);
        context.fill(0,0,w,h,0x22000000);
    }
}
