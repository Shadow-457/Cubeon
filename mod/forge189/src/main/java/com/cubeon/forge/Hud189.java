package com.cubeon.forge;

import com.cubeon.client.hud.*;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.*;
import net.minecraft.client.renderer.GlStateManager;
import net.minecraft.client.network.NetworkPlayerInfo;
import net.minecraft.entity.EntityLivingBase;
import net.minecraft.entity.player.EntityPlayer;
import net.minecraft.item.ItemStack;
import net.minecraft.potion.*;
import net.minecraft.util.BlockPos;
import net.minecraftforge.client.event.RenderLivingEvent;
import java.util.*;

public final class Hud189 extends Gui {
    private static final ArrayDeque<Long> LEFT = new ArrayDeque<>(), RIGHT = new ArrayDeque<>();
    private static Object comboTarget, world;
    private static int combo;
    private static long comboAt;
    private static float lastHealth;
    public static void click(int button, boolean down) {
        if (!down || !CubeonForge.eligible()) return;
        ArrayDeque<Long> list = button == 0 ? LEFT : button == 1 ? RIGHT : null;
        if (list != null) { if (list.size() >= 128) list.removeFirst(); list.addLast(System.nanoTime()); }
    }
    private static int cps(ArrayDeque<Long> values) {
        long now = System.nanoTime();
        while (!values.isEmpty() && now - values.peekFirst() >= 1000000000L) values.removeFirst();
        return values.size();
    }
    public static boolean enabled(HudFeatures f) {
        CubeonHudConfig c = CubeonHudConfig.get();
        switch (f) {
            case FPS: return c.showFps; case KEYS: return c.showKeys;
            case ARMOR: return c.showArmor; case PING: return c.showPing; case CPS: return c.showCps;
            default: return c.extraEnabled(f.slot);
        }
    }
    public static void toggle(HudFeatures f) {
        CubeonHudConfig c = CubeonHudConfig.get();
        switch (f) {
            case FPS: c.showFps = !c.showFps; break; case KEYS: c.showKeys = !c.showKeys; break;
            case ARMOR: c.showArmor = !c.showArmor; break; case PING: c.showPing = !c.showPing; break;
            case CPS: c.showCps = !c.showCps; break; default: c.extra(f.slot).enabled = !c.extra(f.slot).enabled;
        }
        CubeonHudConfig.save();
    }
    public static float position(HudFeatures f, boolean y) {
        CubeonHudConfig c = CubeonHudConfig.get();
        switch (f) {
            case FPS: return y ? c.fpsY : c.fpsX; case KEYS: return y ? c.keysY : c.keysX;
            case ARMOR: return y ? c.armorY : c.armorX; case PING: return y ? c.pingY : c.pingX;
            case CPS: return y ? c.cpsY : c.cpsX; default: return y ? c.extra(f.slot).y : c.extra(f.slot).x;
        }
    }
    public static void position(HudFeatures f, float x, float y) {
        x = CubeonHudConfig.clamp01(x); y = CubeonHudConfig.clamp01(y);
        CubeonHudConfig c = CubeonHudConfig.get();
        switch (f) {
            case FPS: c.fpsX=x; c.fpsY=y; break; case KEYS: c.keysX=x; c.keysY=y; break;
            case ARMOR: c.armorX=x; c.armorY=y; break; case PING: c.pingX=x; c.pingY=y; break;
            case CPS: c.cpsX=x; c.cpsY=y; break; default: c.extra(f.slot).x=x; c.extra(f.slot).y=y;
        }
    }
    public static String label(HudFeatures f) {
        String s = f.slot; return Character.toUpperCase(s.charAt(0)) + s.substring(1);
    }
    public static void draw(float partial, boolean edit) {
        Minecraft mc = Minecraft.getMinecraft();
        if (!edit && (mc.thePlayer == null || mc.theWorld == null || mc.gameSettings.hideGUI || mc.gameSettings.showDebugInfo)) return;
        if (world != mc.theWorld) { world=mc.theWorld; combo=0; comboTarget=null; LEFT.clear(); RIGHT.clear(); lastHealth=0; }
        if (mc.thePlayer != null) {
            if (mc.thePlayer.getHealth() < lastHealth) combo = 0;
            lastHealth = mc.thePlayer.getHealth();
        }
        if (System.nanoTime() - comboAt > 3000000000L) combo=0;
        ScaledResolution r = new ScaledResolution(mc);
        for (HudFeatures f : HudFeatures.ALL) {
            if (!edit && !enabled(f)) continue;
            float scale = CubeonHudConfig.get().scaleFor(f.slot);
            int x = Math.round(position(f,false) * Math.max(0,r.getScaledWidth()-f.width*scale));
            int y = Math.round(position(f,true) * Math.max(0,r.getScaledHeight()-f.height*scale));
            GlStateManager.pushMatrix(); GlStateManager.translate(x,y,0); GlStateManager.scale(scale,scale,1);
            drawRect(0,0,f.width,f.height, enabled(f) ? 0x96202c32 : 0x7030393e);
            if (edit) { drawRect(0,0,f.width,1,0xff7edac5); }
            paint(f,partial,edit);
            GlStateManager.popMatrix();
        }
        GlStateManager.color(1,1,1,1);
    }
    private static void text(String s, int x, int y) {
        Minecraft.getMinecraft().fontRendererObj.drawStringWithShadow(s,x,y,0xffeaf5f3);
    }
    private static void paint(HudFeatures f, float partial, boolean preview) {
        Minecraft mc = Minecraft.getMinecraft(); EntityPlayer p = mc.thePlayer;
        if (p == null && f != HudFeatures.FPS && f != HudFeatures.CLOCK && f != HudFeatures.SYSTEM) { text(label(f),3,2); return; }
        switch(f) {
            case FPS: text(Minecraft.getDebugFPS()+" FPS",3,2); break;
            case CPS: text(cps(LEFT)+" | "+cps(RIGHT)+" CPS",3,2); break;
            case PING:
                NetworkPlayerInfo info = mc.getNetHandler() == null ? null : mc.getNetHandler().getPlayerInfo(p.getUniqueID());
                text((info == null ? 0 : info.getResponseTime())+" ms",3,2); break;
            case CLOCK: text(new java.text.SimpleDateFormat("HH:mm:ss").format(new Date()),3,2); break;
            case SYSTEM:
                Runtime rt=Runtime.getRuntime(); text("RAM "+((rt.totalMemory()-rt.freeMemory())/1048576)+" / "+rt.maxMemory()/1048576+" MB",3,2);
                text(rt.availableProcessors()+" CPU threads",3,13); break;
            case COORDINATES:
                text(String.format(Locale.ROOT,"XYZ %.1f %.1f %.1f",p.posX,p.posY,p.posZ),3,2);
                text("Chunk "+(((int)Math.floor(p.posX))>>4)+", "+(((int)Math.floor(p.posZ))>>4),3,13); break;
            case DIRECTION:
                String[] dirs={"South","Southwest","West","Northwest","North","Northeast","East","Southeast"};
                int d=((int)Math.floor(p.rotationYaw/45+.5)&7); text(dirs[d]+" "+Math.round(p.rotationYaw%360)+"°",3,2); break;
            case BIOME: text(mc.theWorld.getBiomeGenForCoords(new BlockPos(p)).biomeName,3,2); break;
            case DAYLIGHT:
                long ticks=mc.theWorld.getWorldTime(); long clock=(ticks+6000)%24000;
                text(String.format(Locale.ROOT,"World %02d:%02d",clock/1000,(clock%1000)*60/1000),3,2);
                text("Day "+(ticks/24000+1)+(mc.theWorld.isRaining()?" · Rain":" · Clear"),3,13); break;
            case COMBO: text(combo+" Combo",3,2); break;
            case POTIONS:
                int row=0;
                for (PotionEffect effect : p.getActivePotionEffects()) {
                    if (row++>=6) break;
                    Potion pot=Potion.potionTypes[effect.getPotionID()];
                    text(net.minecraft.client.resources.I18n.format(pot.getName())+" "+(effect.getAmplifier()+1)+" "+Potion.getDurationString(effect),3,2+(row-1)*12);
                }
                if (row==0 && preview) text("No effects",3,2); break;
            case ARMOR:
                boolean[] show={CubeonHudConfig.get().showArmorFeet,CubeonHudConfig.get().showArmorLegs,CubeonHudConfig.get().showArmorChest,CubeonHudConfig.get().showArmorHelmet};
                int at=2;
                for(int i=3;i>=0;i--) if(show[i]) {
                    ItemStack item=p.inventory.armorInventory[i];
                    if(item!=null) {
                        net.minecraft.client.renderer.RenderHelper.enableGUIStandardItemLighting();
                        mc.getRenderItem().renderItemAndEffectIntoGUI(item,at,1);
                        net.minecraft.client.renderer.RenderHelper.disableStandardItemLighting();
                        if(item.isItemStackDamageable()) text(""+(item.getMaxDamage()-item.getItemDamage()),at,18);
                    }
                    at+=24;
                }
                break;
            case KEYS:
                key("W",24,2,mc.gameSettings.keyBindForward.isKeyDown()); key("A",2,24,mc.gameSettings.keyBindLeft.isKeyDown());
                key("S",24,24,mc.gameSettings.keyBindBack.isKeyDown()); key("D",46,24,mc.gameSettings.keyBindRight.isKeyDown());
                key("L",2,47,mc.gameSettings.keyBindAttack.isKeyDown()); key("R",35,47,mc.gameSettings.keyBindUseItem.isKeyDown());
                text("Space"+(mc.gameSettings.keyBindJump.isKeyDown()?" ●":""),12,66); break;
        }
    }
    private static void key(String name,int x,int y,boolean on) {
        drawRect(x,y,x+18,y+18,on?0xb957a28e:0x70233035); text(name,x+6,y+5);
    }
    public static void hit(Object target) {
        if (target != comboTarget) { comboTarget=target; combo=0; }
        combo++; comboAt=System.nanoTime();
    }
    public static void health(RenderLivingEvent.Specials.Post event) {
        Minecraft mc=Minecraft.getMinecraft(); EntityLivingBase e=event.entity;
        if(!CubeonHudConfig.get().showEnemyHealth || mc.thePlayer==null || e==mc.thePlayer || e.isInvisible()
                || e.getDistanceSqToEntity(mc.thePlayer)>1024 || !e.isEntityAlive() || !mc.thePlayer.canEntityBeSeen(e)) return;
        GlStateManager.pushMatrix();
        GlStateManager.translate(event.x,event.y+e.height+.3,event.z);
        GlStateManager.rotate(-mc.getRenderManager().playerViewY,0,1,0);
        GlStateManager.rotate(mc.getRenderManager().playerViewX,1,0,0);
        GlStateManager.scale(-.025,-.025,.025);
        GlStateManager.disableLighting(); GlStateManager.disableCull();
        drawRect(-20,0,20,4,0xb0202b30);
        drawRect(-20,0,-20+Math.round(40*Math.max(0,Math.min(1,e.getHealth()/Math.max(1,e.getMaxHealth())))),4,0xe67edac5);
        GlStateManager.enableCull(); GlStateManager.enableLighting(); GlStateManager.popMatrix();
    }
}
