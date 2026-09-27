"""
Compiles the Cubeon Client mod's *Minecraft-facing* code - the screen, the mod
entrypoint, and the pause-menu mixin - against a hand-written stub of the
Minecraft API.

Why a stub instead of a real Minecraft jar: building against real Minecraft needs
Gradle, a network connection, mappings, and a JDK matching whichever Minecraft
version is targeted. That means the ~900 lines of UI code, which is where the
mod's user-visible bugs actually live, would otherwise get no automated check at
all. Compiling against a stub catches everything a compiler catches - typos,
wrong arities, ambiguous overloads, unreachable code, a lambda that resolves to
the wrong functional interface - without any of that machinery.

The stub is also a contract, and that is the more valuable half. It declares
exactly the slice of Minecraft API this mod is allowed to touch: the calls whose
shape has not changed from 1.20 through 26.x and beyond. What it leaves out
matters more than what it contains - there is no GuiGraphics, no Screen.render,
and no mouseClicked/mouseScrolled/keyPressed, because every one of those changed
signature in 26.x. A screen built from widgets alone compiles for both namespace
eras from one source tree; a screen that overrides render or an input callback
needs two. Reach for a method the stub omits, or for LinearLayout (which did not
exist in 1.20.1), and this test fails - before a jar built against one version
turns out to be broken on another. Any addition here is a deliberate decision to
narrow the mod's version range, so adding to the stub should feel like it costs
something.

What this does NOT prove: that the stub matches real Minecraft. It is written
from the real signatures, but only an actual Gradle build against a real
Minecraft jar can confirm them.

Skips cleanly (exit 0) when no JDK with javac is installed.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from test_mod_bridge import find_jdk, _java_version  # noqa: E402

MOD_SOURCES = [
    "mod/src/main/java/com/cubeon/client/Json.java",
    "mod/src/main/java/com/cubeon/client/Bridge.java",
    "mod/src/main/java/com/cubeon/client/CubeonClientScreen.java",
    "mod/src/main/java/com/cubeon/client/CubeonClient.java",
    "mod/src/main/java/com/cubeon/client/BadgeNames.java",
    "mod/src/main/java/com/cubeon/client/TabListTag.java",
    "mod/src/main/java/com/cubeon/client/modules/ModuleCategory.java",
    "mod/src/main/java/com/cubeon/client/modules/Module.java",
    "mod/src/main/java/com/cubeon/client/modules/ModuleConfig.java",
    "mod/src/main/java/com/cubeon/client/modules/HudText.java",
    "mod/src/main/java/com/cubeon/client/modules/HudState.java",
    "mod/src/main/java/com/cubeon/client/modules/GameOptions.java",
    "mod/src/main/java/com/cubeon/client/modules/OptionsAccessor.java",
    "mod/src/main/java/com/cubeon/client/modules/Modules.java",
    "mod/src/main/java/com/cubeon/client/keys/MenuKey.java",
    "mod/src/main/java/com/cubeon/client/ModuleMenuScreen.java",
    "mod/src/main/java/com/cubeon/client/MenuPaint.java",
    "mod/src/main/java/com/cubeon/client/MenuPainter.java",
    "mod/src/main/java/com/cubeon/client/WorldPlayers.java",
    "mod/src/main/java/com/cubeon/client/mixin/PauseScreenMixin.java",
    "mod/src/main/java-overlay-1.20-1.21/com/cubeon/client/MenuPaintImpl.java",
    "mod/src/main/java-overlay-1.20-1.21/com/cubeon/client/mixin/HudMixin.java",
    "mod/src/main/java-overlay-1.20-1.21/com/cubeon/client/mixin/MenuPaintMixin.java",
    "mod/src/main/java/com/cubeon/client/mixin/PlayerTickMixin.java",
    "mod/src/main/java/com/cubeon/client/mixin/PlayerTabOverlayMixin.java",
    "mod/src/main/java/com/cubeon/client/mixin/TitleScreenMixin.java",
    # The 1.20-1.21 overlay: CornerIcon's era-stable copy. The 26.x overlay is
    # NOT compiled here - it draws through the 26-only GuiGraphicsExtractor /
    # FontDescription chain, so it would pollute the stub with types that do
    # not exist on 1.20. That copy is checked by the real 26 build instead.
    "mod/src/main/java-overlay-1.20-1.21/com/cubeon/client/CornerIcon.java",
]

# The mod targets Java 17 bytecode (mod/build.gradle explains why), so the stub
# compile targets it too - that way a Java 21-only construct fails here rather
# than at mixin-apply time in someone's game.
RELEASE = "17"

# ---------------------------------------------------------------------------
# The allowlist. Every entry is API whose signature is unchanged across the
# Minecraft versions in mod/brackets.json.
# ---------------------------------------------------------------------------

STUBS = {
    "net/minecraft/ChatFormatting.java": """
        package net.minecraft;

        public enum ChatFormatting {
            AQUA, RED, WHITE, GRAY, GREEN, GOLD, YELLOW
        }
        """,

    "net/minecraft/network/chat/Component.java": """
        package net.minecraft.network.chat;

        import net.minecraft.util.FormattedCharSequence;

        /** Real Minecraft declares this as an interface with static factories. */
        public interface Component {
            String getString();

            /**
             * The text sequence the mod draws menu labels through. 1.21 removed
             * GuiGraphics' String overload of drawString, so this is the only
             * cross-version route to a rendered label.
             */
            FormattedCharSequence getVisualOrderText();

            static MutableComponent literal(String text) {
                return new MutableComponent(text);
            }

            static MutableComponent empty() {
                return new MutableComponent("");
            }
        }
        """,

    "net/minecraft/network/chat/MutableComponent.java": """
        package net.minecraft.network.chat;

        import net.minecraft.ChatFormatting;

        public final class MutableComponent implements Component {
            private final String text;

            public MutableComponent(String text) {
                this.text = text;
            }

            @Override
            public String getString() {
                return text;
            }

            @Override
            public net.minecraft.util.FormattedCharSequence
                    getVisualOrderText() {
                return null;
            }

            public MutableComponent append(Component other) {
                return this;
            }

            public MutableComponent withStyle(ChatFormatting formatting) {
                return this;
            }

            public MutableComponent withStyle(Style style) {
                return this;
            }
        }
        """,

    "net/minecraft/network/chat/Style.java": """
        package net.minecraft.network.chat;

        import net.minecraft.ChatFormatting;

        /*
         * Only what the mod styles with. withColor(TextColor) and
         * withColor(ChatFormatting) both exist in 1.20.1 and 26.1.2 (javap'd in
         * both real jars), which is why the Cubeon-green tab tag can be exact
         * rather than approximated with ChatFormatting.GREEN - whose chat green
         * is a different colour, and was all the old nametag badge could use
         * on the 1.20-1.21 bracket.
         *
         * The real class also has withColor(int); deliberately NOT modelled,
         * because it erases against withColor(TextColor) in a bare stub and the
         * mod has no reason to reach for it - the int form is not what gives
         * the exact green, TextColor.fromRgb is.
         */
        public final class Style {
            public static final Style EMPTY = new Style();

            public Style withColor(TextColor color) {
                return this;
            }

            public Style withColor(ChatFormatting formatting) {
                return this;
            }
        }
        """,

    "net/minecraft/network/chat/TextColor.java": """
        package net.minecraft.network.chat;

        /* fromRgb(int) is the one factory; present unchanged in both eras. */
        public final class TextColor {
            public static TextColor fromRgb(int rgb) {
                return new TextColor();
            }
        }
        """,

    "net/minecraft/client/gui/Font.java": """
        package net.minecraft.client.gui;

        public class Font {
            /** The one text measurement whose shape has never changed. */
            public int width(String text) {
                return text.length() * 6;
            }
        }
        """,

    "net/minecraft/client/gui/components/StringWidget.java": """
        package net.minecraft.client.gui.components;

        import net.minecraft.client.gui.Font;
        import net.minecraft.network.chat.Component;

        /**
         * A one-line label. Note what is absent: setColor and alignLeft, which
         * 26.x dropped. Colour comes from the Component's own style instead,
         * and Component styling has never moved.
         */
        public class StringWidget extends AbstractWidget {
            public StringWidget(int x, int y, int width, int height, Component message,
                                Font font) {
            }
        }
        """,

    "net/minecraft/client/gui/components/Renderable.java": """
        package net.minecraft.client.gui.components;

        public interface Renderable {
        }
        """,

    "net/minecraft/client/gui/components/events/GuiEventListener.java": """
        package net.minecraft.client.gui.components.events;

        public interface GuiEventListener {
        }
        """,

    "net/minecraft/client/gui/narration/NarratableEntry.java": """
        package net.minecraft.client.gui.narration;

        public interface NarratableEntry {
        }
        """,

    "net/minecraft/client/gui/components/Tooltip.java": """
        package net.minecraft.client.gui.components;

        import net.minecraft.network.chat.Component;

        public final class Tooltip {
            public static Tooltip create(Component message) {
                return new Tooltip();
            }
        }
        """,

    "net/minecraft/client/gui/components/AbstractWidget.java": """
        package net.minecraft.client.gui.components;

        import net.minecraft.client.gui.components.events.GuiEventListener;
        import net.minecraft.client.gui.narration.NarratableEntry;
        import net.minecraft.network.chat.Component;

        public abstract class AbstractWidget
                implements Renderable, GuiEventListener, NarratableEntry {

            public boolean visible = true;
            public boolean active = true;

            public int getX() {
                return 0;
            }

            public int getY() {
                return 0;
            }

            public int getWidth() {
                return 0;
            }

            public int getHeight() {
                return 0;
            }

            public void setX(int x) {
            }

            public void setY(int y) {
            }

            public void setBounds(int x, int y, int width, int height) {
            }

            public void setWidth(int width) {
            }

            public void setMessage(Component message) {
            }

            /** Accepts null, which is how a tooltip is cleared. */
            public void setTooltip(Tooltip tooltip) {
            }
        }
        """,

    "net/minecraft/client/gui/components/Button.java": """
        package net.minecraft.client.gui.components;

        import net.minecraft.network.chat.Component;

        public class Button extends AbstractWidget {

            public interface OnPress {
                void onPress(Button button);
            }

            public static Builder builder(Component message, OnPress onPress) {
                return new Builder();
            }

            public static final class Builder {
                public Builder bounds(int x, int y, int width, int height) {
                    return this;
                }

                public Builder tooltip(Tooltip tooltip) {
                    return this;
                }

                public Button build() {
                    return new Button();
                }
            }
        }
        """,

    "net/minecraft/client/gui/components/EditBox.java": """
        package net.minecraft.client.gui.components;

        import net.minecraft.client.gui.Font;
        import net.minecraft.network.chat.Component;

        import java.util.function.Consumer;

        public class EditBox extends AbstractWidget {

            public EditBox(Font font, int x, int y, int width, int height, Component message) {
            }

            public void setMaxLength(int length) {
            }

            public void setValue(String value) {
            }

            public String getValue() {
                return "";
            }

            public void setResponder(Consumer<String> responder) {
            }

            public void setHint(Component hint) {
            }

            /**
             * Editability is setEditable(), not the inherited `active` field:
             * EditBox's own key handling does not consult `active`, so a box
             * disabled with active = false would still accept typing.
             */
            public void setEditable(boolean editable) {
            }
        }
        """,

    "net/minecraft/client/gui/Gui.java": """
        package net.minecraft.client.gui;

        import net.minecraft.network.chat.Component;

        public class Gui {
            /*
             * The overlay line above the hotbar. Deliberately the only way this
             * mod says anything outside its own screen: getChat().addMessage and
             * SystemToast's factories have both been reshuffled between eras (by
             * 26.x addMessage is private and takes four arguments), and neither
             * appears in this stub so neither can be reached for by accident.
             */
            public void setOverlayMessage(Component message, boolean animated) {
            }
        }
        """,

    "net/minecraft/client/player/LocalPlayer.java": """
        package net.minecraft.client.player;

        import net.minecraft.network.chat.Component;
        import net.minecraft.world.entity.player.Player;

        /* The local player. Extends Player, as in the real game - the HUD
         * modules are typed to Player so they are not tied to this class. */
        public class LocalPlayer extends Player {
            /**
             * The one chat entry point this mod is allowed: present with the
             * same shape in 1.20-26.x (displayClientMessage was renamed away
             * by 26.x; this wasn't). Always the chat window.
             */
            public void sendSystemMessage(Component message) {
            }
        }
        """,

    "net/minecraft/client/gui/screens/Screen.java": """
        package net.minecraft.client.gui.screens;

        import net.minecraft.client.Minecraft;
        import net.minecraft.client.gui.Font;
        import net.minecraft.client.gui.components.Renderable;
        import net.minecraft.client.gui.components.events.GuiEventListener;
        import net.minecraft.client.gui.narration.NarratableEntry;
        import net.minecraft.network.chat.Component;

        import java.util.List;

        /*
         * Note what is absent, because that absence is the whole contract: no
         * render, no mouseClicked/mouseReleased/mouseDragged/mouseScrolled, no
         * keyPressed. Every one of those changed signature in 26.x - drawing moved
         * to a render-state extractor, and the input callbacks now take event
         * objects - so a mod that overrides any of them needs one source tree per
         * era. Leaving them out of the stub means the compiler refuses the
         * @Override before that can happen. What is left is lifecycle plus
         * addRenderableWidget: the framework draws the widgets and routes clicks
         * to them, and that arrangement has not moved since 1.20.
         */
        public abstract class Screen implements GuiEventListener, Renderable {

            public int width;
            public int height;
            protected Minecraft minecraft;
            protected final Font font = new Font();
            protected final Component title;

            protected Screen(Component title) {
                this.title = title;
            }

            protected void init() {
            }

            public void tick() {
            }

            public void removed() {
            }

            public void onClose() {
            }

            /**
             * Drops every widget, so init() can rebuild the whole layout from
             * scratch - the mod menu does this whenever the category tab or
             * the search text changes. Verified present with the same shape in
             * 1.20.1 and 26.1.2, and rebuildWidgets() is the alternative if this
             * ever moves.
             */
            public void clearWidgets() {
            }

            public boolean isPauseScreen() {
                return false;
            }

            protected <T extends GuiEventListener & Renderable & NarratableEntry> T
                    addRenderableWidget(T widget) {
                return widget;
            }

            public List<? extends GuiEventListener> children() {
                return List.of();
            }
        }
        """,

    "net/minecraft/client/gui/screens/PauseScreen.java": """
        package net.minecraft.client.gui.screens;

        import net.minecraft.network.chat.Component;

        public class PauseScreen extends Screen {
            public PauseScreen(boolean showPauseMenu) {
                super(Component.empty());
            }
        }
        """,

    "net/minecraft/client/gui/screens/TitleScreen.java": """
        package net.minecraft.client.gui.screens;

        import net.minecraft.network.chat.Component;

        public class TitleScreen extends Screen {
            public TitleScreen() {
                super(Component.empty());
            }
        }
        """,

    "net/minecraft/client/Minecraft.java": """
        package net.minecraft.client;

        import net.minecraft.client.gui.Gui;
        import net.minecraft.client.gui.screens.Screen;
        import net.minecraft.client.multiplayer.ClientPacketListener;
        import net.minecraft.client.player.LocalPlayer;

        public class Minecraft {

            public Screen screen;
            public LocalPlayer player;
            public Gui gui;
            /** What the crosshair is on - how the reach module is computed. */
            public net.minecraft.world.phys.HitResult hitResult;
            public net.minecraft.client.Options options;
            public User user;

            public static Minecraft getInstance() {
                return new Minecraft();
            }

            /** Runs the task on the client thread. The mod's only way back. */
            public void execute(Runnable task) {
            }

            public void setScreen(Screen screen) {
            }

            public boolean hasSingleplayerServer() {
                return false;
            }

            /** Frames per second, for the FPS module. */
            public int getFps() {
                return 0;
            }

            /** The game's font, for drawing HUD text. */
            public net.minecraft.client.gui.Font font;

            /**
             * The game session's account info. Real signature checked against
             * the shipped 26.1.2 jar: `public net.minecraft.client.User
             * getUser()` (User declared as net.minecraft.client.User there;
             * Yarn/Mojang maps it the same across 1.20.1-26.x, loom remaps the
             * obfuscated brackets). Used only as a display-label fallback -
             * never identity, never an editable field.
             */
            public User getUser() {
                return null;
            }

            /**
             * The player-list handle. Same name and return type from 1.20.1
             * through 26.1.2 (checked against the shipped 26.1.2 jar); null
             * outside a world, which is how the menu's Online panel knows it
             * is in a menu. Added for WorldPlayers - a deliberate narrowing:
             * if a future version renames this, WorldPlayers is the file that
             * moves, per era.
             */
            public ClientPacketListener getConnection() {
                return null;
            }
        }
        """,

    "net/minecraft/client/User.java": """
        package net.minecraft.client;

        /**
         * The signed-in account record. Real signature checked against the
         * shipped 26.1.2 jar: `public java.lang.String getName()`, unchanged
         * across every bracket (loom remaps the obfuscated ones).
         */
        public class User {

            public String getName() {
                return "";
            }
        }
        """,

    "org/lwjgl/glfw/GLFW.java": """
        package org.lwjgl.glfw;

        /*
         * Only what the mod's menu keybind uses. GLFW is a NATIVE library, so
         * unlike Minecraft's own classes this API is identical on every
         * version - which is the whole reason the keybind reads the key
         * through here instead of a per-bracket KeyMapping.
         */
        public final class GLFW {
            public static final int GLFW_KEY_K = 75;
            public static final int GLFW_PRESS = 1;

            public static long glfwGetCurrentContext() {
                return 0L;
            }

            public static int glfwGetKey(long window, int key) {
                return 0;
            }
        }
        """,

    "net/minecraft/client/Options.java": """
        package net.minecraft.client;

        import net.minecraft.client.OptionInstance;

        /*
         * Only what the mod's Render modules touch. Every accessor here was
         * javap'd in the real 1.20.1 AND 26.1.2 jars and exists with the same
         * shape in both - that is the whole reason the modules are written
         * against the accessor form and never the public FIELD form
         * (options.gammaSetting), which only survives on the older bracket.
         * Adding a real option here needs that same check, and a note saying
         * which jar it was checked in.
         */
        public final class Options {
            public final KeyMapping keyUp = new KeyMapping();
            public final KeyMapping keyDown = new KeyMapping();
            public final KeyMapping keyLeft = new KeyMapping();
            public final KeyMapping keyRight = new KeyMapping();
            public final KeyMapping keyJump = new KeyMapping();
            public final KeyMapping keySprint = new KeyMapping();

            /** Still a plain public field in both eras, unlike the rest. */
            public boolean smoothCamera;

            public OptionInstance<Double> gamma() {
                return new OptionInstance<>();
            }

            public OptionInstance<Integer> fov() {
                return new OptionInstance<>();
            }

            public OptionInstance<Boolean> bobView() {
                return new OptionInstance<>();
            }
        }
        """,

    "net/minecraft/client/OptionInstance.java": """
        package net.minecraft.client;

        /* get/set verified identical in 1.20.1 and 26.1.2. */
        public final class OptionInstance<T> {
            public T get() {
                return null;
            }

            public void set(T value) {
            }
        }
        """,

    "net/minecraft/client/KeyMapping.java": """
        package net.minecraft.client;

        public class KeyMapping {
            public boolean isDown() {
                return false;
            }
        }
        """,

    "net/minecraft/world/entity/player/Player.java": """
        package net.minecraft.world.entity.player;

        import net.minecraft.network.chat.Component;
        import net.minecraft.world.entity.LivingEntity;

        /*
         * The local player, as the HUD and auto-sprint modules see it. Every
         * member here was javap'd in the real 1.20.1 and 26.1.2 jars: the HUD
         * layer is shared between brackets, so anything it calls has to exist
         * in both or one bracket fails to build.
         *
         * getDisplayName/getName are the retired nametag badge's target and are
         * kept only so the shape stays documented; nothing calls them now.
         */
        public class Player extends LivingEntity {
            /*
             * NOTE: there is deliberately no `input` field here. The movement
             * input is the one thing that did NOT survive both brackets - 1.20.1
             * has a public `input.forwardImpulse` field, 26.x has
             * ClientInput.hasForwardImpulse() - and auto-sprint reads the forward
             * KEYBIND instead precisely so it stays in shared source. Do not add
             * an input stub back without checking both jars.
             */

            public double getX() { return 0.0; }
            public double getY() { return 0.0; }
            public double getZ() { return 0.0; }

            public double distanceToSqr(double x, double y, double z) { return 0.0; }

            public float getAttackStrengthScale(float base) { return 0.0F; }

            public boolean isSprinting() { return false; }
            public void setSprinting(boolean sprinting) { }

            public Component getName() { return Component.empty(); }
            public Component getDisplayName() { return Component.empty(); }
        }
        """,

    "net/minecraft/world/entity/LivingEntity.java": """
        package net.minecraft.world.entity;

        /* Only what the modules read off the player. */
        public class LivingEntity extends Entity {
            public int getArmorValue() { return 0; }
        }
        """,

    "net/minecraft/util/FormattedCharSequence.java": """
        package net.minecraft.util;

        /*
         * Minecraft's own text-sequence interface (NOT java.util's - there
         * isn't one). This is the type the mod draws menu labels through,
         * because 1.21 removed GuiGraphics' String overload of drawString and
         * this overload is the one that survives in both eras.
         */
        public interface FormattedCharSequence {
        }
        """,

    "net/minecraft/client/gui/GuiGraphics.java": """
        package net.minecraft.client.gui;

        import net.minecraft.client.gui.Font;
        import net.minecraft.util.FormattedCharSequence;

        /*
         * The 1.20-1.21 HUD draw context. Deliberately NOT part of the 26.x
         * bracket: that era renders through GuiGraphicsExtractor, which is why
         * HudMixin has a per-bracket copy but everything above it is shared.
         */
        public class GuiGraphics {
            public void fill(int x1, int y1, int x2, int y2, int colour) {
            }

            public void fill(int x1, int y1, int x2, int y2, int colour, int alpha) {
            }

            public int drawString(Font font, String text, int x, int y, int colour) {
                return 0;
            }

            public int drawString(Font font, String text, int x, int y, int colour,
                                   boolean shadow) {
                return 0;
            }

            /**
             * The overload that SURVIVES 1.21: 1.21 removed the String form
             * (the game log proved it with a NoSuchMethodError), and this one
             * exists in 1.20.1 too, so drawing through it is what lets one
             * source cover the whole 1.20-1.21 bracket.
             */
            public int drawString(Font font, FormattedCharSequence text, int x,
                    int y, int colour, boolean shadow) {
                return 0;
            }
        }
        """,

    "net/minecraft/client/gui/Gui.java": """
        package net.minecraft.client.gui;

        import net.minecraft.network.chat.Component;

        public class Gui {
            /*
             * The overlay line above the hotbar. Deliberately the only way this
             * mod says anything outside its own screen: getChat().addMessage and
             * SystemToast's factories have both been reshuffled between eras (by
             * 26.x addMessage is private and takes four arguments), and neither
             * appears in this stub so neither can be reached for by accident.
             */
            public void setOverlayMessage(Component message, boolean animated) {
            }

            /*
             * The HUD draw entry point, for the 1.20-1.21 HudMixin only. 26.x
             * replaced it with extractRenderState, which is why that mixin has a
             * per-bracket copy - see HudMixin. The constructor is deliberately
             * absent: nothing constructs a Gui, and stubbing its parameters would
             * mean dragging ItemRenderer in for no reason.
             */
            public void render(GuiGraphics graphics, float partialTick) {
            }
        }
        """,

    "net/fabricmc/loader/api/FabricLoader.java": """
        package net.fabricmc.loader.api;

        import java.nio.file.Path;

        /* Loader (not a Fabric API module) - where the module config lives. */
        public interface FabricLoader {
            static FabricLoader getInstance() {
                return null;
            }

            Path getConfigDir();
        }
        """,

    "net/minecraft/world/entity/Entity.java": """
        package net.minecraft.world.entity;

        /* Only what the reach module needs off an entity hit. */
        public class Entity {
            public double distanceTo(Entity other) { return 0.0; }
        }
        """,

    "net/minecraft/world/phys/Vec3.java": """
        package net.minecraft.world.phys;

        /* The hit-result location the reach module reads. */
        public class Vec3 {
            public double getX() { return 0.0; }
            public double getY() { return 0.0; }
            public double getZ() { return 0.0; }
        }
        """,

    "net/minecraft/world/phys/BlockPos.java": """
        package net.minecraft.world.phys;

        public class BlockPos {
            public int getX() { return 0; }
            public int getY() { return 0; }
            public int getZ() { return 0; }
        }
        """,

    "net/minecraft/world/phys/HitResult.java": """
        package net.minecraft.world.phys;

        /* Type and location, the only two things the reach module reads. */
        public class HitResult {
            public enum Type {
                MISS, BLOCK, ENTITY
            }

            public Type getType() { return Type.MISS; }
            public Vec3 getLocation() { return new Vec3(); }
        }
        """,

    "net/minecraft/world/phys/BlockHitResult.java": """
        package net.minecraft.world.phys;

        public class BlockHitResult extends HitResult {
            public BlockPos getBlockPos() { return new BlockPos(); }
        }
        """,

    "net/minecraft/world/phys/EntityHitResult.java": """
        package net.minecraft.world.phys;

        import net.minecraft.world.entity.Entity;

        public class EntityHitResult extends HitResult {
            public Entity getEntity() { return null; }
        }
        """,

    "net/minecraft/client/User.java": """
        package net.minecraft.client;

        /* getName() is what the ping module looks the player up by. */
        public class User {
            public String getName() {
                return "";
            }
        }
        """,

    "net/minecraft/client/multiplayer/ClientPacketListener.java": """
        package net.minecraft.client.multiplayer;

        import java.util.Collection;

        public class ClientPacketListener {
            public Collection<PlayerInfo> getOnlinePlayers() {
                return java.util.List.of();
            }

            /** The player list, for the ping module. */
            public PlayerInfo getPlayerInfo(String name) {
                return null;
            }
        }
        """,

    "net/minecraft/client/multiplayer/PlayerInfo.java": """
        package net.minecraft.client.multiplayer;

        import com.mojang.authlib.GameProfile;

        /*
         * One row of the tab list, and also the online-player list
         * ClientPacketListener hands out. getProfile() is the whole surface the
         * mod needs: it is how a row's Minecraft username is read, and authlib
         * is an external library that has never been version-reshaped, so
         * GameProfile.getName() is safe on every version this mod serves.
         * getLatency() is the ping module's only other use.
         */
        public class PlayerInfo {
            public GameProfile getProfile() {
                return null;
            }

            public int getLatency() {
                return 0;
            }
        }
        """,

    "com/mojang/authlib/GameProfile.java": """
        package com.mojang.authlib;

        /*
         * Modelled at its authlib 6 shape (plain class, getName()). authlib 7
         * turned it into a record with name(), and the mod resolves whichever
         * exists reflectively at runtime - see TabListTag.nameOf - because that
         * rename lands INSIDE the 1.20-1.21 bracket's own range (1.20.1 ships
         * authlib 6, 1.21.11 ships 7), so no single compile-time spelling can
         * serve the whole bracket. getName() is modelled so the reflective
         * lookup is actually exercised at class-init rather than quietly
         * finding nothing and untagging every row.
         */
        public class GameProfile {
            public String getName() {
                return "";
            }
        }
        """,

    "net/fabricmc/api/ClientModInitializer.java": """
        package net.fabricmc.api;

        public interface ClientModInitializer {
            void onInitializeClient();
        }
        """,

    "org/slf4j/Logger.java": """
        package org.slf4j;

        public interface Logger {
            void info(String message);

            void warn(String message);

            void warn(String message, Throwable throwable);
        }
        """,

    "org/slf4j/LoggerFactory.java": """
        package org.slf4j;

        public final class LoggerFactory {
            public static Logger getLogger(String name) {
                return new Logger() {
                    @Override
                    public void info(String message) {
                    }

                    @Override
                    public void warn(String message) {
                    }

                    @Override
                    public void warn(String message, Throwable throwable) {
                    }
                };
            }

            private LoggerFactory() {
            }
        }
        """,

    "org/spongepowered/asm/mixin/Mixin.java": """
        package org.spongepowered.asm.mixin;

        import java.lang.annotation.ElementType;
        import java.lang.annotation.Retention;
        import java.lang.annotation.RetentionPolicy;
        import java.lang.annotation.Target;

        @Retention(RetentionPolicy.RUNTIME)
        @Target(ElementType.TYPE)
        public @interface Mixin {
            Class<?>[] value() default {};

            String[] targets() default {};
        }
        """,

    "org/spongepowered/asm/mixin/injection/At.java": """
        package org.spongepowered.asm.mixin.injection;

        import java.lang.annotation.ElementType;
        import java.lang.annotation.Retention;
        import java.lang.annotation.RetentionPolicy;
        import java.lang.annotation.Target;

        @Retention(RetentionPolicy.RUNTIME)
        @Target({ElementType.ANNOTATION_TYPE, ElementType.METHOD})
        public @interface At {
            String value();
        }
        """,

    "org/spongepowered/asm/mixin/injection/Inject.java": """
        package org.spongepowered.asm.mixin.injection;

        import java.lang.annotation.ElementType;
        import java.lang.annotation.Retention;
        import java.lang.annotation.RetentionPolicy;
        import java.lang.annotation.Target;

        @Retention(RetentionPolicy.RUNTIME)
        @Target(ElementType.METHOD)
        public @interface Inject {
            String[] method();

            At[] at();

            int require() default -1;

            boolean cancellable() default false;
        }
        """,

    "org/spongepowered/asm/mixin/injection/callback/CallbackInfo.java": """
        package org.spongepowered.asm.mixin.injection.callback;

        public class CallbackInfo {
            /** Only meaningful when the injector is cancellable=true. */
            public void cancel() {
            }
        }
        """,

    "org/spongepowered/asm/mixin/injection/callback/CallbackInfoReturnable.java": """
        package org.spongepowered.asm.mixin.injection.callback;

        public class CallbackInfoReturnable<T> extends CallbackInfo {
            public T getReturnValue() {
                return null;
            }

            public void setReturnValue(T value) {
            }
        }
        """,

    "net/minecraft/client/gui/components/PlayerTabOverlay.java": """
        package net.minecraft.client.gui.components;

        import net.minecraft.client.multiplayer.PlayerInfo;
        import net.minecraft.network.chat.Component;

        /*
         * The tab list. Only getNameForDisplay is declared: it is the one
         * method the Cubeon mixin needs, and it is identical in 1.20.1 and
         * 26.1.2 (verified with javap against both real jars) even though the
         * render path around it is not - 1.20-1.21 has
         * render(GuiGraphics, ...) where 26.x has
         * extractRenderState(GuiGraphicsExtractor, ...). The renderer is
         * deliberately ABSENT: if a future change ever needs it, that needs a
         * real justification here per era, not a copy of this shell.
         */
        public class PlayerTabOverlay {
            public Component getNameForDisplay(PlayerInfo info) {
                return Component.empty();
            }
        }
        """,
}


def _dedent(source):
    lines = source.strip("\n").splitlines()
    pad = min((len(l) - len(l.lstrip()) for l in lines if l.strip()), default=0)
    return "\n".join(l[pad:] if l.strip() else "" for l in lines) + "\n"


def _check_mixin_wiring():
    """The mixin config, MOD_SOURCES and build_mod_jars must agree.

    The [Cubeon] tab tag is three moving parts: the mixin, its registration in
    cubeon-client.mixins.json, and the two build lists. Disagreement is never a
    soft warning - an unregistered mixin silently does NOTHING in-game, and a
    stale REQUIRED_ENTRIES entry fails a real build over a class that no longer
    exists (that is exactly how the removed nametag badge surfaced). It is
    cheap to check, so it is checked before anything is compiled.
    """
    ok = True

    def say(good, label, detail=""):
        nonlocal ok
        print(("  ok   " if good else "  FAIL ") + label
              + (f"\n       {detail}" if not good and detail else ""))
        ok = ok and good

    with open(os.path.join(ROOT, "mod", "src", "main", "resources",
                           "cubeon-client.mixins.json"), encoding="utf-8") as fh:
        registered = set(json.load(fh).get("client", []))

    jar_src = open(os.path.join(ROOT, "tools", "build_mod_jars.py"),
                   encoding="utf-8").read()

    for name in sorted(registered):
        # A mixin may be SHARED (src/main/java) or PER-BRACKET (one copy in
        # each src/main/java-overlay-<key>, like HudMixin and CornerIcon, which
        # target game calls that were genuinely reshaped between eras). The
        # config names it either way, so both spellings are accepted here - but
        # a per-bracket mixin must exist in EVERY overlay, or one bracket
        # silently ships without it.
        shared = f"mod/src/main/java/com/cubeon/client/mixin/{name}.java"
        overlays = sorted(glob.glob(
            f"mod/src/main/java-overlay-*/com/cubeon/client/mixin/{name}.java"))
        if os.path.isfile(os.path.join(ROOT, shared)):
            say(shared in MOD_SOURCES, f"{name}.java (shared) is in MOD_SOURCES")
        else:
            say(len(overlays) > 0,
                f"{name} is per-bracket and has an overlay copy", shared)
            say(len(overlays) == 2,
                f"{name} exists in both bracket overlays",
                f"found {len(overlays)}; a missing one ships that bracket "
                f"without the mixin and the feature silently does nothing")
        say(f"{name}.class" in jar_src,
            f"{name}.class is in build_mod_jars REQUIRED_ENTRIES")

    # A mixin that targets one of the mod's OWN classes must name a method that
    # class actually DECLARES. Mixin resolves @Inject against the target's own
    # methods, so an inherited one is not found - and with require = 0 that is a
    # SILENT no-op, not a failure. This is not hypothetical: MenuPaintMixin
    # aimed at ModuleMenuScreen for `render`, which ModuleMenuScreen only
    # inherits from Screen, so the whole mod menu never painted, every string
    # was missing, and the test suite stayed green throughout.
    own = {}
    for path in glob.glob("mod/src/main/java/com/cubeon/client/**/*.java",
                          recursive=True):
        src = open(path, encoding="utf-8").read()
        simple = os.path.basename(path)[:-5]
        fqn = ("com.cubeon.client.mixin." if
               os.path.basename(os.path.dirname(path)) == "mixin"
               else "com.cubeon.client.") + simple
        own[fqn] = src
        # Also index the simple name: a mixin lives in ...client.mixin but
        # imports its target from ...client, so resolving against the mixin's
        # own package would miss the very case this guard exists for.
        own.setdefault(simple, src)

    for path in MOD_SOURCES:
        if "/mixin/" not in path.replace(os.sep, "/"):
            continue
        src = open(os.path.join(ROOT, path), encoding="utf-8").read()
        # Anchored and MULTILINE on purpose: a javadoc that mentions
        # `@Mixin(Other.class)` while explaining a bug must not be mistaken
        # for the real annotation - which it was, and produced a false
        # failure on the very fix this guard was written for.
        m = re.search(r"^\s*@Mixin\(([\w.]+)\.class\)", src, re.M)
        if not m:
            continue
        target = m.group(1)
        if target not in own:
            continue      # a Minecraft class - the javap evidence lives in the
                           # overlay comment instead
        for injected in re.findall(r'@Inject\(method\s*=\s*"([^"]+)"', src):
            declared = re.search(rf"\b{re.escape(injected)}\s*\(", own[target])
            say(declared is not None,
                f"{os.path.basename(path)}: {target.split('.')[-1]}"
                f".{injected}() is declared by its own target",
                "Mixin resolves @Inject against the target class's OWN methods; "
                "an inherited one is silently not found when require = 0 and the "
                "feature just never runs")

    for path in MOD_SOURCES:
        name = os.path.basename(path)
        if "/mixin/" in path.replace(os.sep, "/"):
            say(name[:-5] in registered,
                f"{name[:-5]} (in MOD_SOURCES) is registered in the mixin config",
                "a compiled-but-unregistered mixin does nothing at runtime")

    # The tag is TAB LIST ONLY. The nametag badge was removed deliberately.
    say("PlayerNameMixin" not in registered,
        "the removed nametag mixin is NOT registered",
        "the [Cubeon] tag is tab-list only; a nametag badge must not come back")
    say("PlayerNameMixin.java" not in jar_src,
        "the removed nametag mixin is gone from build_mod_jars")
    say("PlayerNameMixin.java" not in "\n".join(MOD_SOURCES),
        "the removed nametag mixin is gone from MOD_SOURCES")

    # The cross-era seam, and the user-visible contract.
    mixin = open(os.path.join(ROOT, "mod/src/main/java/com/cubeon/client/mixin/"
                                  "PlayerTabOverlayMixin.java"),
                 encoding="utf-8").read()
    say('method = "getNameForDisplay"' in mixin,
        "the mixin still targets getNameForDisplay (the cross-era seam)",
        "re-check BOTH jars (1.20.1 and 26.1.2) before retargeting it: the "
        "renderer differs between eras but this method does not")
    say("require = 0" in mixin,
        "the mixin stays non-required, so a moved method loses the tag not the game")
    say("Throwable" in mixin, "the per-frame injection swallows everything")

    tag = open(os.path.join(ROOT, "mod/src/main/java/com/cubeon/client/"
                                  "TabListTag.java"), encoding="utf-8").read()
    say('"[Cubeon]"' in tag, "the tag text is [Cubeon]")
    say("0x83C13D" in tag, "the tag uses the exact Cubeon green")
    say("TextColor.fromRgb" in tag,
        "the green goes through TextColor.fromRgb (present in both eras)")
    return ok


def main():
    javac, _java = find_jdk()
    if not javac:
        print("SKIP  no working JDK found; the mod's Minecraft-facing code was "
              "not compile-checked (the Python suite is unaffected)")
        return 0

    print("\nmixin wiring (mixin config <-> MOD_SOURCES <-> build_mod_jars)")
    if not _check_mixin_wiring():
        return 1

    missing = [s for s in MOD_SOURCES if not os.path.isfile(os.path.join(ROOT, s))]
    if missing:
        print("FAIL  missing mod sources: " + ", ".join(missing))
        return 1

    print(f"using {javac} (javac {_java_version(javac)}), targeting release {RELEASE}")
    work = tempfile.mkdtemp(prefix="cubeon-mod-stub-")
    try:
        stub_dir = os.path.join(work, "stubs")
        written = []
        for relative, source in STUBS.items():
            path = os.path.join(stub_dir, relative)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(_dedent(source))
            written.append(path)

        stub_out = os.path.join(work, "stub-classes")
        build = subprocess.run(
            [javac, "--release", RELEASE, "-nowarn", "-d", stub_out] + written,
            capture_output=True, text=True, timeout=180)
        if build.returncode != 0:
            print("FAIL  the API stub itself does not compile (fix this test):\n")
            print((build.stdout + build.stderr).strip())
            return 1
        print(f"  ok  API stub compiles ({len(written)} types)")

        mod_out = os.path.join(work, "mod-classes")
        compile_mod = subprocess.run(
            [javac, "--release", RELEASE, "-Xlint:all", "-Werror",
             "-cp", stub_out, "-d", mod_out]
            + [os.path.join(ROOT, s) for s in MOD_SOURCES],
            capture_output=True, text=True, cwd=ROOT, timeout=180)
        output = (compile_mod.stdout + compile_mod.stderr).strip()
        if compile_mod.returncode != 0:
            print("FAIL  the mod's Minecraft-facing code does not compile against "
                  "the allowed API subset:\n")
            print(output)
            print("\nIf the call it is complaining about is genuinely stable across "
                  "every bracket in mod/brackets.json, add it to STUBS in this file "
                  "- deliberately, and with the signature copied from real "
                  "Minecraft. If it is not, the mod cannot use it.")
            return 1
        if output:
            print(output)
        for source in MOD_SOURCES:
            print("  ok  " + os.path.basename(source))
        print("\nall mod sources compile clean against the version-stable API subset")
        return 0
    except subprocess.TimeoutExpired:
        print("FAIL  the stub compile timed out")
        return 1
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
