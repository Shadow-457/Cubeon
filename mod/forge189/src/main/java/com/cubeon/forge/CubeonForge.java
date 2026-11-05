package com.cubeon.forge;

import com.cubeon.client.Bridge;
import com.cubeon.client.cosmetics.*;
import com.cubeon.client.emotes.*;
import com.cubeon.client.hud.*;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.*;
import net.minecraft.client.settings.KeyBinding;
import net.minecraft.util.ChatComponentText;
import net.minecraftforge.common.MinecraftForge;
import net.minecraftforge.fml.common.Mod;
import net.minecraftforge.fml.common.event.FMLInitializationEvent;
import net.minecraftforge.fml.common.eventhandler.SubscribeEvent;
import net.minecraftforge.fml.common.gameevent.TickEvent;
import net.minecraftforge.fml.client.registry.ClientRegistry;
import net.minecraftforge.client.event.*;
import org.lwjgl.input.Keyboard;
import org.lwjgl.input.Mouse;
import java.util.*;

@Mod(modid="cubeonclient", name="Cubeon Client", version="1.0.0", clientSideOnly=true,
     acceptedMinecraftVersions="[1.8.9]", acceptableRemoteVersions="*")
public final class CubeonForge {
    public static final KeyBinding MENU = key("Cubeon Client", Keyboard.KEY_RSHIFT);
    public static final KeyBinding ZOOM = key("Zoom", Keyboard.KEY_C);
    public static final KeyBinding FREELOOK = key("Freelook", Keyboard.KEY_LMENU);
    public static final KeyBinding EMOTES = key("Emotes", Keyboard.KEY_B);
    public static final KeyBinding WINGS = key("Wing action", Keyboard.KEY_N);
    private Object world;
    private String room = "";
    private List<Bridge.EmoteEvent> previous = Collections.emptyList();
    private final java.util.concurrent.ArrayBlockingQueue<Bridge.Toast> toasts = new java.util.concurrent.ArrayBlockingQueue<>(32);
    private static KeyBinding key(String name, int code) { return new KeyBinding(name, code, "Cubeon Client"); }
    public static boolean eligible() {
        Minecraft mc = Minecraft.getMinecraft();
        return mc.thePlayer != null && mc.theWorld != null && mc.currentScreen == null && mc.inGameHasFocus && mc.thePlayer.isEntityAlive();
    }
    public static boolean held(KeyBinding key) {
        int code = key.getKeyCode();
        return code < 0 ? Mouse.isButtonDown(code + 100) : code > 0 && Keyboard.isKeyDown(code);
    }
    @Mod.EventHandler public void init(FMLInitializationEvent event) {
        CubeonHudConfig.load();
        for (KeyBinding key : new KeyBinding[]{MENU, ZOOM, FREELOOK, EMOTES, WINGS}) ClientRegistry.registerKeyBinding(key);
        CosmeticSelection.bind(Minecraft.getMinecraft().mcDataDir.toPath().resolve("config/" + CosmeticSelection.FILE_NAME));
        Bridge.get().setToastSink(toast -> { if (!toasts.offer(toast)) { toasts.poll(); toasts.offer(toast); } });
        Bridge.get().start();
        MinecraftForge.EVENT_BUS.register(this);
        net.minecraftforge.fml.common.FMLCommonHandler.instance().bus().register(this);
        Cosmetics189.install();
    }
    @SubscribeEvent public void tick(TickEvent.ClientTickEvent event) {
        if (event.phase != TickEvent.Phase.END) return;
        Minecraft mc = Minecraft.getMinecraft();
        CubeonHudConfig config = CubeonHudConfig.get();
        if (MENU.isPressed() && mc.currentScreen == null) mc.displayGuiScreen(new ClientScreen(null));
        if (EMOTES.isPressed() && eligible() && config.showEmotes) mc.displayGuiScreen(new EmoteScreen());
        if (mc.thePlayer != null) {
            mc.gameSettings.thirdPersonView = Freelook.INSTANCE.update(held(FREELOOK), eligible(), mc.thePlayer, mc.theWorld,
                    mc.thePlayer.rotationYaw, mc.thePlayer.rotationPitch, mc.gameSettings.thirdPersonView);
            if (config.autoSprint && eligible() && mc.thePlayer.moveForward > .8f && !mc.thePlayer.isSneaking()
                    && !mc.thePlayer.isCollidedHorizontally && (mc.thePlayer.getFoodStats().getFoodLevel() > 6 || mc.thePlayer.capabilities.allowFlying))
                mc.thePlayer.setSprinting(true);
            WingAction.INSTANCE.tick(held(WINGS), WINGS.isPressed(), eligible(), mc.thePlayer, mc.theWorld,
                    CosmeticSelection.selectedWing(), (mc.thePlayer.ticksExisted) / 20f);
        } else Freelook.INSTANCE.update(false, false, null, null, 0, 0, mc.gameSettings.thirdPersonView);
        String address = mc.thePlayer == null || !config.showEmotes ? "" : mc.getCurrentServerData() == null
                ? "single:" + mc.thePlayer.getUniqueID() : mc.getCurrentServerData().serverIP;
        if (world != mc.theWorld || !room.equals(address)) {
            world = mc.theWorld; room = address; previous = Collections.emptyList();
            EmoteState.reset(); Bridge.get().setEmoteRoom(address.isEmpty() ? "" : EmoteRoom.hash(address));
        }
        if (mc.thePlayer != null && !mc.isGamePaused() && config.showEmotes) {
            EmoteState.tick();
            List<Bridge.EmoteEvent> fresh = Bridge.get().emotes();
            if (fresh != previous) { EmoteState.sync(fresh); previous = fresh; }
            if (EmoteState.playing(mc.thePlayer.getUniqueID()) && (mc.thePlayer.motionX * mc.thePlayer.motionX
                    + mc.thePlayer.motionZ * mc.thePlayer.motionZ > .0004 || mc.gameSettings.keyBindJump.isKeyDown()
                    || mc.gameSettings.keyBindAttack.isKeyDown() || mc.gameSettings.keyBindUseItem.isKeyDown()
                    || mc.thePlayer.ridingEntity != null || !mc.thePlayer.isEntityAlive())) play(-1);
        }
        Bridge.Toast toast;
        while (mc.thePlayer != null && (toast = toasts.poll()) != null)
            mc.thePlayer.addChatMessage(new ChatComponentText("[Cubeon] " + toast.text()));
        CosmeticSelection.refresh();
    }
    public static void play(int id) {
        Minecraft mc = Minecraft.getMinecraft();
        if (mc.thePlayer == null || mc.theWorld == null || !CubeonHudConfig.get().showEmotes || id >= EmoteState.NAMES.length) return;
        int serial = EmoteState.play(mc.thePlayer.getUniqueID(), mc.thePlayer.getName(), id);
        Bridge.get().sendEmote(mc.thePlayer.getUniqueID().toString(), id < 0 ? "stop" : EmoteState.NAMES[id], serial);
    }
    @SubscribeEvent public void menu(GuiScreenEvent.InitGuiEvent.Post event) {
        if (event.gui instanceof GuiMainMenu || event.gui instanceof GuiIngameMenu) {
            int y = 8;
            // Avoid existing right-edge buttons from other mods.
            for (GuiButton button : event.buttonList)
                if (button.xPosition + button.getButtonWidth() > event.gui.width - 110 && button.yPosition < y + 20)
                    y = button.yPosition + 23;
            event.buttonList.add(new GuiButton(45891, event.gui.width - 108, y, 100, 20, "Cubeon Client"));
        }
    }
    @SubscribeEvent public void click(GuiScreenEvent.ActionPerformedEvent.Post event) {
        if (event.button.id == 45891) Minecraft.getMinecraft().displayGuiScreen(new ClientScreen(event.gui));
    }
    @SubscribeEvent public void mouse(MouseEvent event) {
        Hud189.click(event.button, event.buttonstate);
        if (eligible() && Freelook.INSTANCE.scroll(event.dwheel / 120.0)) event.setCanceled(true);
    }
    @SubscribeEvent public void fov(EntityViewRenderEvent.FOVModifier event) {
        if (eligible() && held(ZOOM)) event.setFOV(event.getFOV() / CubeonHudConfig.get().zoomFactor);
    }
    @SubscribeEvent public void hud(RenderGameOverlayEvent.Post event) {
        if (event.type == RenderGameOverlayEvent.ElementType.ALL) Hud189.draw(event.partialTicks, false);
    }
    @SubscribeEvent public void health(RenderLivingEvent.Specials.Post event) { Hud189.health(event); }
}
