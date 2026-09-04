"""
Compiles the Cubeon Friends mod's *Minecraft-facing* code - the screen, the mod
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
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

from test_mod_bridge import find_jdk, _java_version  # noqa: E402

MOD_SOURCES = [
    "mod/src/main/java/com/cubeon/friends/Json.java",
    "mod/src/main/java/com/cubeon/friends/Bridge.java",
    "mod/src/main/java/com/cubeon/friends/CubeonFriendsScreen.java",
    "mod/src/main/java/com/cubeon/friends/CubeonFriendsClient.java",
    "mod/src/main/java/com/cubeon/friends/mixin/PauseScreenMixin.java",
    "mod/src/main/java/com/cubeon/friends/mixin/TitleScreenMixin.java",
    # The 1.20-1.21 overlay: CornerIcon's era-stable copy. The 26.x overlay is
    # NOT compiled here - it draws the icon through FontDescription, which is
    # 26-only API, so it would pollute the stub with types that do not exist
    # on 1.20. That copy is checked by the real 26 build instead.
    "mod/src/main/java-overlay-1.20-1.21/com/cubeon/friends/CornerIcon.java",
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

        /** Real Minecraft declares this as an interface with static factories. */
        public interface Component {
            String getString();

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

            public MutableComponent append(Component other) {
                return this;
            }

            public MutableComponent withStyle(ChatFormatting formatting) {
                return this;
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

        public class LocalPlayer {
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
        import net.minecraft.client.player.LocalPlayer;

        public class Minecraft {

            public Screen screen;
            public LocalPlayer player;
            public Gui gui;

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
        }
        """,

    "org/spongepowered/asm/mixin/injection/callback/CallbackInfo.java": """
        package org.spongepowered.asm.mixin.injection.callback;

        public class CallbackInfo {
        }
        """,
}


def _dedent(source):
    lines = source.strip("\n").splitlines()
    pad = min((len(l) - len(l.lstrip()) for l in lines if l.strip()), default=0)
    return "\n".join(l[pad:] if l.strip() else "" for l in lines) + "\n"


def main():
    javac, _java = find_jdk()
    if not javac:
        print("SKIP  no working JDK found; the mod's Minecraft-facing code was "
              "not compile-checked (the Python suite is unaffected)")
        return 0

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
