package comparison;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import net.minecraft.client.Minecraft;
import net.minecraft.client.InactivityFpsLimit;
import net.minecraft.client.CameraType;
import net.minecraft.client.GraphicsPreset;
import net.minecraft.client.CloudStatus;
import net.minecraft.server.level.ParticleStatus;
import net.minecraft.client.gui.screens.TitleScreen;
import net.minecraft.client.gui.screens.options.VideoSettingsScreen;
import net.minecraft.world.level.GameType;
import net.minecraft.world.level.gamerules.GameRules;
import net.minecraft.world.clock.WorldClocks;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Unique;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;
import java.nio.file.*;
import java.util.*;

/** Temporary measurement mod. All world changes require its explicit load command. */
@Mixin(Minecraft.class)
public class FrameProbe {
 @Unique private Path comparison$root;
 @Unique private String comparison$client, comparison$lastCommand = "";
 @Unique private long comparison$poll, comparison$start, comparison$last;
 @Unique private boolean comparison$initialized, comparison$loading, comparison$scene, comparison$running;
 @Unique private int comparison$run;
 @Unique private int comparison$runs = 2;
 @Unique private double comparison$warmup = 15, comparison$duration = 30;
 @Unique private boolean comparison$auto, comparison$settings;
 @Unique private long comparison$readyAt, comparison$settingsAt, comparison$sceneAt;
 @Unique private final List<Long> comparison$frames = new ArrayList<>();
 @Unique private final Set<String> comparison$invalid = new HashSet<>();

 @Unique private void comparison$status(String value) throws Exception {
  Files.writeString(comparison$root.resolve(comparison$client + "-status.txt"), value + "\n");
  System.out.println("CLIENT_COMPARISON " + comparison$client + " " + value);
 }

 @Inject(method="runTick", at=@At("RETURN"))
 private void comparison$frame(boolean render, CallbackInfo ci) throws Exception {
  Minecraft mc = (Minecraft)(Object)this;
  if (!comparison$initialized) {
   comparison$initialized = true;
   Path file = mc.gameDirectory.toPath().resolve("config/client-comparison.json");
   if (!Files.exists(file)) return;
   JsonObject cfg = JsonParser.parseString(Files.readString(file)).getAsJsonObject();
   comparison$root = Path.of(cfg.get("output").getAsString());
   comparison$client = cfg.get("client").getAsString();
   comparison$auto = cfg.has("auto") && cfg.get("auto").getAsBoolean();
   if (cfg.has("runs")) comparison$runs = cfg.get("runs").getAsInt();
   if (cfg.has("warmup")) comparison$warmup = cfg.get("warmup").getAsDouble();
   if (cfg.has("duration")) comparison$duration = cfg.get("duration").getAsDouble();
   comparison$status("game ready; waiting for settings/load command");
  }
  if (comparison$root == null || !render) return;
  long now = System.nanoTime();
  // Initial loading can replace both Options and screens. Wait for the final title.
  if (comparison$auto && !comparison$settings && mc.isGameLoadFinished()
      && mc.gui.screen() instanceof TitleScreen && mc.gui.overlay() == null) {
   if (comparison$readyAt == 0) comparison$readyAt = now;
   if (now - comparison$readyAt > 3_000_000_000L) {
    mc.options.graphicsPreset().set(GraphicsPreset.FAST);
    mc.options.renderDistance().set(6);
    mc.options.simulationDistance().set(5);
    mc.options.biomeBlendRadius().set(0);
    mc.options.particles().set(ParticleStatus.MINIMAL);
    mc.options.ambientOcclusion().set(false);
    mc.options.entityShadows().set(false);
    mc.options.entityDistanceScaling().set(0.75);
    mc.options.mipmapLevels().set(2);
    mc.options.cloudStatus().set(CloudStatus.FAST);
    mc.options.enableVsync().set(false);
    mc.options.framerateLimit().set(260);
    mc.options.fov().set(70);
    mc.options.gamma().set(0.5);
    mc.options.guiScale().set(3);
    mc.options.inactivityFpsLimit().set(InactivityFpsLimit.MINIMIZED);
    mc.options.pauseOnLostFocus = false;
    mc.options.save();
    Files.writeString(comparison$root.resolve(comparison$client + "-effective-options.txt"), mc.options.dumpOptionsForReport());
    mc.setScreenAndShow(new VideoSettingsScreen(mc.gui.screen(), mc, mc.options));
    comparison$settings = true; comparison$settingsAt = now;
    comparison$status("showing matched video settings");
   }
  }
  if (comparison$auto && comparison$settings && !comparison$loading
      && now - comparison$settingsAt > 8_000_000_000L) {
   comparison$loading = true;
   mc.createWorldOpenFlows().openWorld("Cubeon FastClient Benchmark", () -> mc.gui.setScreen(new TitleScreen()));
   comparison$status("loading copied benchmark world");
  }
  // No file IO during sampling. Idle controls are checked at most four times/second.
  if (!comparison$running && now - comparison$poll > 250_000_000L) {
   comparison$poll = now;
   Path control = comparison$root.resolve(comparison$client + "-control.txt");
   String command = Files.exists(control) ? Files.readString(control).trim() : "";
   if (!command.equals(comparison$lastCommand)) {
    comparison$lastCommand = command;
    String action = command.split(" ")[0];
    if (action.equals("settings") && mc.player == null && mc.gui.screen() != null) {
     mc.gui.setScreen(new VideoSettingsScreen(mc.gui.screen(), mc, mc.options));
     Files.writeString(comparison$root.resolve(comparison$client + "-effective-options.txt"), mc.options.dumpOptionsForReport());
     comparison$status("showing video settings");
    } else if (action.equals("load") && mc.player == null && !comparison$loading) {
     comparison$loading = true;
     mc.createWorldOpenFlows().openWorld("Cubeon FastClient Benchmark", () -> mc.gui.setScreen(new TitleScreen()));
     comparison$status("loading copied benchmark world");
    } else if (action.equals("arm") && comparison$scene && mc.player != null && mc.gui.screen() == null) {
     comparison$running = true;
     comparison$start = comparison$last = 0;
     comparison$status("benchmark armed; 3 x (30s warmup + 60s measurement)");
    }
   }
  }
  if (comparison$loading && !comparison$scene && mc.player != null && mc.getSingleplayerServer() != null) {
   comparison$scene = true;
   comparison$sceneAt = now;
   var server = mc.getSingleplayerServer();
   var id = mc.player.getUUID();
   server.execute(() -> {
    var player = server.getPlayerList().getPlayer(id);
    if (player == null) return;
    var level = server.overworld();
    server.getGameRules().set(GameRules.ADVANCE_TIME, false, server);
    server.getGameRules().set(GameRules.ADVANCE_WEATHER, false, server);
    server.getGameRules().set(GameRules.SPAWN_MOBS, false, server);
    server.getGameRules().set(GameRules.RANDOM_TICK_SPEED, 0, server);
    var clock = server.registryAccess().getOrThrow(WorldClocks.OVERWORLD);
    server.clockManager().setTotalTicks(clock, 6000L);
    server.clockManager().setPaused(clock, true);
    level.getWeatherData().setRaining(false);
    level.getWeatherData().setThundering(false);
    player.setGameMode(GameType.SPECTATOR);
    player.teleportTo(level, 199.07647766714268, 113.0, 92.49004533510325, Set.of(), 0, 0, true);
   });
   mc.options.setCameraType(CameraType.FIRST_PERSON);
   mc.options.pauseOnLostFocus = false;
   comparison$status("scene ready; waiting for arm command");
  }
  if (comparison$auto && comparison$scene && comparison$run == 0 && !comparison$running
      && mc.player != null && mc.gui.screen() == null && now - comparison$sceneAt > 5_000_000_000L) {
   comparison$running = true;
   comparison$start = comparison$last = 0;
   comparison$status("measuring " + comparison$runs + " samples");
  }
  if (!comparison$running) return;
  if (mc.player == null || mc.level == null || mc.gui.screen() != null || mc.getWindow().isIconified()) {
   comparison$invalid.add("world interrupted, menu opened, or window minimized");
   comparison$running = false;
   comparison$status("INVALID: world interrupted, menu opened, or window minimized");
   return;
  }
  mc.options.inactivityFpsLimit().set(InactivityFpsLimit.MINIMIZED);
  mc.getFramerateLimitTracker().onInputReceived();
  if (comparison$start == 0) {
   comparison$start = now;
   Files.writeString(comparison$root.resolve(comparison$client + "-runtime.txt"),
    "Java " + System.getProperty("java.version") + "\nMax heap " + Runtime.getRuntime().maxMemory() +
    "\nFramebuffer " + mc.getWindow().getWidth() + "x" + mc.getWindow().getHeight() +
    "\nPosition " + mc.player.getX() + "," + mc.player.getY() + "," + mc.player.getZ() + "\n");
  }
  double seconds = (now - comparison$start) / 1e9;
  mc.player.setYRot((float)(seconds * 6));
  mc.player.setXRot(0);
  if (seconds >= comparison$warmup && seconds < comparison$warmup + comparison$duration && comparison$last != 0) {
   comparison$frames.add(now - comparison$last);
   if (mc.getFramerateLimitTracker().getThrottleReason().toString().equals("NONE") == false)
    comparison$invalid.add("frame throttling");
   if (Math.abs(mc.player.getX() - 199.07647766714268) > .05 || Math.abs(mc.player.getY() - 113) > .05 || Math.abs(mc.player.getZ() - 92.49004533510325) > .05)
    comparison$invalid.add("camera position changed");
   if (mc.getWindow().getWidth() != 1280 || mc.getWindow().getHeight() != 720)
    comparison$invalid.add("framebuffer is not 1280x720");
   if (mc.options.renderDistance().get() != 6 || mc.options.simulationDistance().get() != 5
       || mc.options.enableVsync().get() || mc.options.framerateLimit().get() != 260)
    comparison$invalid.add("effective graphics settings changed");
  }
  comparison$last = now;
  if (seconds >= comparison$warmup + comparison$duration) {
   comparison$run++;
   StringBuilder csv = new StringBuilder("frame_ns\n");
   for (long frame : comparison$frames) csv.append(frame).append('\n');
   Files.writeString(comparison$root.resolve(comparison$client + "-" + comparison$run + ".csv"), csv);
   Files.writeString(comparison$root.resolve(comparison$client + "-" + comparison$run + "-validation.txt"),
    comparison$invalid.isEmpty() ? "valid\n" : String.join("\n", new TreeSet<>(comparison$invalid)) + "\n");
   comparison$frames.clear(); comparison$invalid.clear();
   comparison$start = comparison$last = 0;
   comparison$status("completed sample " + comparison$run + "/" + comparison$runs);
   if (comparison$run == comparison$runs) { comparison$running = false; comparison$status("complete; game left open for recording"); }
  }
 }
}
