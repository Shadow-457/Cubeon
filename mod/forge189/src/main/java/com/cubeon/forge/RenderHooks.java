package com.cubeon.forge;
import com.cubeon.client.hud.*;
import com.cubeon.client.emotes.*;
import net.minecraft.client.Minecraft;
import net.minecraft.client.model.*;
import net.minecraft.entity.*;
import net.minecraft.entity.player.EntityPlayer;
import java.util.*;

public final class RenderHooks {
    private static final WeakHashMap<ModelPlayer,float[][]> REST=new WeakHashMap<>();
    public static boolean look(Object p,float dx,float dy) { return p==Minecraft.getMinecraft().thePlayer && CubeonForge.eligible() && Freelook.INSTANCE.look(dx,dy); }
    private static boolean free(Object p) { return p==Minecraft.getMinecraft().thePlayer && Freelook.INSTANCE.active(); }
    public static float yaw(Object p) { return free(p)?Freelook.INSTANCE.yaw():((Entity)p).rotationYaw; }
    public static float pitch(Object p) { return free(p)?Freelook.INSTANCE.pitch():((Entity)p).rotationPitch; }
    public static float previousYaw(Object p) { return free(p)?Freelook.INSTANCE.yaw():((Entity)p).prevRotationYaw; }
    public static float previousPitch(Object p) { return free(p)?Freelook.INSTANCE.pitch():((Entity)p).prevRotationPitch; }
    public static float distance(float value) { return Freelook.INSTANCE.active()?(float)Freelook.INSTANCE.distance():value; }
    public static void hit(Object p) { if(p instanceof EntityLivingBase) Hud189.hit(p); }
    private static ModelRenderer[] parts(ModelPlayer m) { return new ModelRenderer[]{m.bipedHead,m.bipedBody,m.bipedRightArm,m.bipedLeftArm,m.bipedRightLeg,m.bipedLeftLeg,
            m.bipedHeadwear,m.bipedBodyWear,m.bipedRightArmwear,m.bipedLeftArmwear,m.bipedRightLegwear,m.bipedLeftLegwear}; }
    public static void restorePose(Object model) {
        ModelPlayer m=(ModelPlayer)model; float[][] rest=REST.remove(m); if(rest==null) return;
        ModelRenderer[] parts=parts(m);
        for(int i=0;i<parts.length;i++) {
            ModelRenderer p=parts[i]; float[] r=rest[i]; p.rotationPointX=r[0]; p.rotationPointY=r[1]; p.rotationPointZ=r[2];
            p.rotateAngleX=r[3]; p.rotateAngleY=r[4]; p.rotateAngleZ=r[5];
        }
    }
    public static void pose(Object model,Object entity,float age) {
        if(!(entity instanceof EntityPlayer) || !CubeonHudConfig.get().showEmotes) return;
        EntityPlayer player=(EntityPlayer)entity;
        if(!player.isEntityAlive() || player.ridingEntity!=null || player.isPlayerSleeping()) return;
        EmotePose pose=EmoteState.frame(player.getUniqueID(),player.getName(),age%1); if(pose==null) return;
        ModelPlayer m=(ModelPlayer)model; ModelRenderer[] parts=parts(m); float[][] rest=new float[parts.length][6];
        for(int i=0;i<parts.length;i++) {
            ModelRenderer p=parts[i]; rest[i]=new float[]{p.rotationPointX,p.rotationPointY,p.rotationPointZ,p.rotateAngleX,p.rotateAngleY,p.rotateAngleZ};
        }
        REST.put(m,rest);
        pose.anchorBody(m.bipedBody.rotationPointX,m.bipedBody.rotationPointY,m.bipedBody.rotationPointZ,
                m.bipedBody.rotateAngleX,m.bipedBody.rotateAngleY,m.bipedBody.rotateAngleZ);
        for(int i=0;i<6;i++) {
            ModelRenderer p=parts[i]; p.rotateAngleX=pose.blend(i,0,p.rotateAngleX); p.rotateAngleY=pose.blend(i,1,p.rotateAngleY); p.rotateAngleZ=pose.blend(i,2,p.rotateAngleZ);
            pose.position(i,p.rotationPointX,p.rotationPointY,p.rotationPointZ);
            p.rotationPointX+=pose.offsets[i*3]; p.rotationPointY+=pose.offsets[i*3+1]; p.rotationPointZ+=pose.offsets[i*3+2];
            ModelBase.copyModelAngles(p,parts[i+6]);
        }
    }
    public static void blur() { Blur189.draw(); }
}
