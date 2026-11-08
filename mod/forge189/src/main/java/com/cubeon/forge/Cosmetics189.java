package com.cubeon.forge;
import com.cubeon.client.cosmetics.*;
import com.cubeon.client.hud.CubeonHudConfig;
import net.minecraft.client.Minecraft;
import net.minecraft.client.entity.AbstractClientPlayer;
import net.minecraft.client.model.*;
import net.minecraft.client.renderer.*;
import net.minecraft.client.renderer.entity.*;
import net.minecraft.client.renderer.entity.layers.LayerRenderer;
import net.minecraft.client.renderer.vertex.DefaultVertexFormats;
import net.minecraft.util.ResourceLocation;
import java.util.*;
import org.lwjgl.opengl.GL11;

public final class Cosmetics189 implements LayerRenderer<AbstractClientPlayer> {
    private final RenderPlayer renderer;
    private final CosmeticAnimation.PosedQuad posed=new CosmeticAnimation.PosedQuad();
    private static final WeakHashMap<AbstractClientPlayer,CosmeticAnimation.Tracker> MOTION=new WeakHashMap<>();
    private static Object world;
    Cosmetics189(RenderPlayer renderer) { this.renderer=renderer; }
    @SuppressWarnings("unchecked") public static void install() {
        try {
            java.lang.reflect.Field layers=null;
            for(java.lang.reflect.Field f:RendererLivingEntity.class.getDeclaredFields()) if(List.class.isAssignableFrom(f.getType())) { layers=f; break; }
            if(layers==null) throw new IllegalStateException("Player render layers missing");
            layers.setAccessible(true);
            java.lang.reflect.Field skins=net.minecraftforge.fml.relauncher.ReflectionHelper.findField(RenderManager.class,"skinMap","field_178636_l");
            skins.setAccessible(true);
            for(RenderPlayer r:((Map<String,RenderPlayer>)skins.get(Minecraft.getMinecraft().getRenderManager())).values())
                ((List<LayerRenderer<?>>)layers.get(r)).add(new Cosmetics189(r));
        } catch(ReflectiveOperationException e) { throw new IllegalStateException("Cubeon player layer registration failed",e); }
    }
    @Override public boolean shouldCombineTextures() { return false; }
    @Override public void doRenderLayer(AbstractClientPlayer p,float limb,float amount,float partial,float age,float yaw,float pitch,float scale) {
        Minecraft mc=Minecraft.getMinecraft(); CubeonHudConfig c=CubeonHudConfig.get();
        if(mc.thePlayer==null || mc.theWorld==null || p.isInvisible() || p.isSpectator()) return;
        if(world!=mc.theWorld) { world=mc.theWorld; MOTION.clear(); }
        RemoteCosmetics.context(world,c.showOtherCosmetics);
        boolean local=p==mc.thePlayer;
        if(!local && (!c.showOtherCosmetics || p.getDistanceSqToEntity(mc.thePlayer)>4096)) return;
        CosmeticSelection.Items selection=local?CosmeticSelection.snapshot():RemoteCosmetics.get(p.getName());
        if(selection.empty()) return;
        CosmeticCatalog.Catalog catalog=CosmeticCatalog.get(); if(catalog==null) return;
        CosmeticAnimation.Tracker tracker=MOTION.get(p);
        if(tracker==null) { tracker=new CosmeticAnimation.Tracker(); MOTION.put(p,tracker); }
        float seconds=(p.ticksExisted+partial)/20f;
        CosmeticAnimation.Frame frame=c.cosmeticAnimations?tracker.sample(seconds,(float)Math.hypot(p.motionX,p.motionZ)*4,false,p.isSprinting(),
                local?WingAction.INSTANCE.elapsed(p,world,seconds):-1):tracker.disabled();
        ModelPlayer model=renderer.getMainModel();
        GL11.glPushAttrib(GL11.GL_ENABLE_BIT|GL11.GL_CURRENT_BIT|GL11.GL_COLOR_BUFFER_BIT|GL11.GL_TEXTURE_BIT);
        try {
            GlStateManager.disableCull(); GlStateManager.enableAlpha(); GlStateManager.alphaFunc(GL11.GL_GREATER,.1f); GlStateManager.color(1,1,1,1);
            for(String slot:CosmeticSelection.SLOTS) {
                if("trail".equals(slot)) continue;
                CosmeticCatalog.Item chosen=catalog.get(selection.get(slot)); if(chosen==null) continue;
                CosmeticCatalog.Item item=chosen.forWingDepth(c.wingDepth);
                GlStateManager.pushMatrix();
                try {
                    if("head".equals(slot)||"face".equals(slot)) model.bipedHead.postRender(scale);
                    else if("hand".equals(slot) || "aura".equals(slot)) { model.bipedRightArm.postRender(scale); GlStateManager.translate(5*scale,-2*scale,0); }
                    else model.bipedBody.postRender(scale);
                    mc.getTextureManager().bindTexture(new ResourceLocation("cubeon-client","textures/cosmetics/"+item.texture));
                    CosmeticAnimation.Frame animation=frame==null?null:frame.forItem(item);
                    WorldRenderer buffer=Tessellator.getInstance().getWorldRenderer(); buffer.begin(GL11.GL_QUADS,DefaultVertexFormats.POSITION_TEX_NORMAL);
                    for(CosmeticGeometry.Quad quad:CosmeticGeometry.quads(item,catalog.anchorX(slot))) {
                        posed.set(quad,animation);
                        for(int i=0;i<4;i++) buffer.pos(posed.x[i]*scale,posed.y[i]*scale,posed.z[i]*scale)
                                .tex(quad.u[i],quad.v[i]).normal(posed.normalX,posed.normalY,posed.normalZ).endVertex();
                    }
                    Tessellator.getInstance().draw();
                } finally { GlStateManager.popMatrix(); }
            }
        } finally { GL11.glPopAttrib(); GlStateManager.color(1,1,1,1); }
    }
}
