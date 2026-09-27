package com.cubeon.client;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

import com.cubeon.client.modules.Module;
import com.cubeon.client.modules.ModuleCategory;
import com.cubeon.client.modules.Modules;

import net.minecraft.client.gui.components.Button;
import net.minecraft.client.gui.components.EditBox;
import net.minecraft.client.gui.components.StringWidget;
import net.minecraft.client.gui.components.Tooltip;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.network.chat.Component;

/**
 * The mod menu: category tabs, a search box, and a card per module with an
 * on/off toggle and its settings.
 *
 * <p>Built entirely from {@link Button}s, {@link EditBox} and
 * {@link StringWidget}. That is a deliberate constraint, not laziness: those
 * three, plus {@code addRenderableWidget} and this class's own {@code font},
 * are the whole widget surface that has not moved between 1.20.1 and 26.x, so
 * one jar serves both brackets. It never overrides {@code render} or an input
 * callback either - a custom render is exactly what changed shape between
 * eras, and cards made of themed buttons look the same everywhere with no
 * per-era drawing code at all.
 */
public class ModuleMenuScreen extends Screen {

    private static final int COLS = 2;
    private static final int CARD_W = 150;
    private static final int CARD_H = 34;
    private static final int CARD_GAP = 4;
    private static final int TAB_Y = 22;
    private static final int LIST_Y = 40;
    private static final int BTN_H = 12;
    private static final int NAME_W = 78;
    private static final int TOGGLE_W = 46;

    private final Screen parent;
    private final List<Module> modules = Modules.get().all();

    private ModuleCategory category = ModuleCategory.ALL;
    private String search = "";
    /** The module whose settings are open, or null for the module list. */
    private Module settingsFor;
    private EditBox searchBox;

    public ModuleMenuScreen(Screen parent) {
        super(Component.literal("Cubeon Modules"));
        this.parent = parent;
    }

    @Override
    protected void init() {
        if (settingsFor != null) {
            buildSettings();
        } else {
            buildList();
        }
    }

    // ---- the module list -------------------------------------------------

    private void buildList() {
        int tabX = 6;
        for (ModuleCategory cat : ModuleCategory.values()) {
            final ModuleCategory chosen = cat;
            addRenderableWidget(Button
                    .builder(Component.literal(cat.label()), b -> {
                        category = chosen;
                        rebuild();
                    })
                    .bounds(tabX, TAB_Y, 44, BTN_H)
                    .build());
            tabX += 46;
        }

        searchBox = new EditBox(this.font, this.width - 92, TAB_Y - 2, 86, 14,
                Component.literal("Search"));
        searchBox.setMaxLength(24);
        searchBox.setValue(search);
        searchBox.setResponder(value -> {
            search = value;
            rebuild();
        });
        addRenderableWidget(searchBox);

        int left = (this.width - (COLS * CARD_W + (COLS - 1) * CARD_GAP)) / 2;
        int y = LIST_Y;
        int col = 0;
        for (Module module : visible()) {
            if (y + CARD_H > this.height - 26) {
                break;   // out of room; Done stays reachable
            }
            int x = left + col * (CARD_W + CARD_GAP);
            addRenderableWidget(Button
                    .builder(Component.literal(module.name()), b -> toggle(module))
                    .bounds(x, y, NAME_W, CARD_H)
                    .tooltip(Tooltip.create(Component.literal(module.description())))
                    .build());
            addRenderableWidget(new StringWidget(x + 2, y + CARD_H - 11,
                    CARD_W - TOGGLE_W - 8, 9,
                    Component.literal(module.description()), this.font));
            addRenderableWidget(Button
                    .builder(Component.literal(module.isEnabled() ? "On" : "Off"),
                            b -> toggle(module))
                    .bounds(x + CARD_W - TOGGLE_W, y + 2, TOGGLE_W, BTN_H)
                    .build());
            if (!module.settingKeys().isEmpty()) {
                addRenderableWidget(Button
                        .builder(Component.literal("..."), b -> {
                            settingsFor = module;
                            rebuild();
                        })
                        .bounds(x + CARD_W - BTN_H - 2, y + CARD_H - BTN_H - 2,
                                BTN_H, BTN_H)
                        .tooltip(Tooltip.create(Component.literal("Settings")))
                        .build());
            }
            col++;
            if (col >= COLS) {
                col = 0;
                y += CARD_H + CARD_GAP;
            }
        }

        addRenderableWidget(Button
                .builder(Component.literal("Done"), b -> onClose())
                .bounds((this.width - 70) / 2, this.height - 20, 70, BTN_H)
                .build());
    }


    private void toggle(Module module) {
        module.setEnabled(!module.isEnabled());
        Modules.get().save();
        rebuild();
    }

    /** Modules passing both the category tab and the search box. */
    private List<Module> visible() {
        String needle = search == null ? "" : search.trim().toLowerCase(Locale.ROOT);
        List<Module> out = new ArrayList<>();
        for (Module module : modules) {
            if (!category.matches(module.category())) {
                continue;
            }
            String name = module.name().toLowerCase(Locale.ROOT);
            String blurb = module.description().toLowerCase(Locale.ROOT);
            if (!needle.isEmpty() && !name.contains(needle)
                    && !blurb.contains(needle)) {
                continue;
            }
            out.add(module);
        }
        return out;
    }

    // ---- one module's settings -------------------------------------------

    private void buildSettings() {
        Module module = settingsFor;
        addRenderableWidget(new StringWidget(8, 14, this.width - 16, 11,
                Component.literal(module.name()), this.font));
        int y = 30;
        for (String key : module.settingKeys()) {
            final boolean isBool = module.isBoolSetting(key);
            addRenderableWidget(new StringWidget(10, y + 3, 150, 9,
                    Component.literal(key + ": " + show(module, key)), this.font));
            addRenderableWidget(Button
                    .builder(Component.literal("-"), b -> {
                        bump(module, key, -1, isBool);
                        rebuild();
                    })
                    .bounds(this.width - 92, y, 16, BTN_H).build());
            addRenderableWidget(Button
                    .builder(Component.literal("+"), b -> {
                        bump(module, key, 1, isBool);
                        rebuild();
                    })
                    .bounds(this.width - 72, y, 16, BTN_H).build());
            y += 16;
        }
        addRenderableWidget(Button
                .builder(Component.literal("Back"), b -> {
                    settingsFor = null;
                    rebuild();
                })
                .bounds((this.width - 70) / 2, this.height - 20, 70, BTN_H)
                .build());
    }

    private static String show(Module module, String key) {
        return module.isBoolSetting(key)
                ? (module.boolValue(key) ? "On" : "Off")
                : Integer.toString(module.intValue(key));
    }

    private static void bump(Module module, String key, int delta, boolean isBool) {
        if (isBool) {
            module.setBoolValue(key, !module.boolValue(key));
        } else {
            module.setIntValue(key, module.intValue(key) + delta * 5);
        }
        // A changed setting only reaches the game while the module is on, so
        // re-apply it here instead of making the player toggle it off and on.
        if (module.isEnabled()) {
            module.setEnabled(false);
            module.setEnabled(true);
        }
        Modules.get().save();
    }

    // ---- plumbing --------------------------------------------------------

    /** Rebuilds the widget set, the way a resize would. */
    private void rebuild() {
        this.clearWidgets();
        init();
    }

    @Override
    public void onClose() {
        Modules.get().save();
        if (minecraft != null) {
            minecraft.setScreen(parent);
        }
    }

    @Override
    public boolean isPauseScreen() {
        return false;
    }
}
