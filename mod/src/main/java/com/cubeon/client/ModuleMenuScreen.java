package com.cubeon.client;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

import com.cubeon.client.modules.Module;
import com.cubeon.client.modules.ModuleCategory;
import com.cubeon.client.modules.Modules;

import net.minecraft.client.gui.Font;
import net.minecraft.client.gui.components.Button;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.network.chat.Component;

/**
 * The mod menu: a dark panel, category tabs, and a card per module.
 *
 * <p><b>It paints itself.</b> The first version of this screen was built from
 * vanilla Button and EditBox widgets, because avoiding any custom drawing is
 * what lets one jar serve both brackets. It worked - and it looked like a
 * Minecraft options screen: grey bevelled buttons in a ragged grid, nothing
 * like a mod menu. This version draws the panel, tabs and cards itself through
 * {@link MenuPaint}, whose two primitives are the only per-bracket part.
 *
 * <p>Inputs are still plain widgets: invisible Buttons sit over every painted
 * element, because {@code mouseClicked} is one of the callbacks whose
 * signature changed in 26.x, and widgets are the cross-era way to get clicks.
 * The buttons draw nothing; {@link #drawOverlay} draws the whole menu.
 *
 * <p>Nothing here overrides {@code render} - see {@code MenuPaintMixin} (one
 * per bracket) for the paint hook.
 */
public class ModuleMenuScreen extends Screen {

    private final Screen parent;
    private final List<Module> modules = Modules.get().all();

    private ModuleCategory category = ModuleCategory.ALL;
    private Module settingsFor;

    // ---- layout, rebuilt on every init/rebuild -------------------------
    // Package-private and mutable because the painter reads them; this class
    // is the only writer, so the picture cannot drift out of step with the
    // invisible hit targets.

    int panelX;
    int panelY;
    int panelW;
    int panelH;
    int gridX;
    int gridY;
    int cols = 1;
    final List<Card> cards = new ArrayList<>();
    final int[] tabX = new int[ModuleCategory.values().length];
    final int[] tabW = new int[ModuleCategory.values().length];
    int[] closeRect = new int[4];
    int[] actionRect = new int[4];
    String settingsTitle = "";
    final List<String> settingLabels = new ArrayList<>();

    private static final int CARD_W = 150;
    private static final int CARD_H = 30;
    private static final int GAP = 6;

    /** One card: shared by the painter and by hit-testing. */
    public static final class Card {
        public final int x;
        public final int y;
        public final int w;
        public final int h;
        public final Module module;

        Card(int x, int y, int w, int h, Module module) {
            this.x = x;
            this.y = y;
            this.w = w;
            this.h = h;
            this.module = module;
        }

        public boolean contains(int mx, int my) {
            return mx >= x && mx < x + w && my >= y && my < y + h;
        }
    }

    public ModuleMenuScreen(Screen parent) {
        super(Component.literal("Cubeon Modules"));
        this.parent = parent;
    }

    @Override
    protected void init() {
        layout();
        buildHitTargets();
    }


    // ---- layout ---------------------------------------------------------

    private void layout() {
        panelW = Math.min(430, this.width - 40);
        panelH = Math.min(256, this.height - 40);
        panelX = (this.width - panelW) / 2;
        panelY = (this.height - panelH) / 2;

        // The column count comes from the panel width, so the grid is always
        // aligned. The first version hard-coded two 150px columns and left the
        // toggles floating outside their own cards, which read as three loose
        // unrelated columns.
        cols = Math.max(1, (panelW - 20) / (CARD_W + GAP));
        int gridW = cols * CARD_W + (cols - 1) * GAP;
        gridX = panelX + (panelW - gridW) / 2;
        gridY = panelY + 48;

        int tx = panelX + 10;
        for (ModuleCategory cat : ModuleCategory.values()) {
            int i = cat.ordinal();
            tabX[i] = tx;
            tabW[i] = 46;
            tx += 48;
        }
        closeRect = new int[]{panelX + panelW - 20, panelY + 6, 14, 14};
        actionRect = new int[]{panelX + (panelW - 70) / 2, panelY + panelH - 20, 70, 14};

        cards.clear();
        settingLabels.clear();
        settingsTitle = "";
        if (settingsFor == null) {
            int y = gridY;
            int col = 0;
            for (Module module : visible()) {
                if (y + CARD_H > panelY + panelH - 26) {
                    break;
                }
                cards.add(new Card(gridX + col * (CARD_W + GAP), y, CARD_W,
                        CARD_H, module));
                col++;
                if (col >= cols) {
                    col = 0;
                    y += CARD_H + GAP;
                }
            }
        } else {
            settingsTitle = settingsFor.name();
            for (String key : settingsFor.settingKeys()) {
                settingLabels.add(key + ": "
                        + (settingsFor.isBoolSetting(key)
                                ? (settingsFor.boolValue(key) ? "On" : "Off")
                                : Integer.toString(settingsFor.intValue(key))));
            }
        }
    }

    /**
     * Invisible buttons over every painted element.
     *
     * <p>They draw nothing at all - the menu is painted by
     * {@link #drawOverlay}. They exist purely so the framework routes clicks,
     * which is the only cross-era way to get input.
     */
    private void buildHitTargets() {
        for (ModuleCategory cat : ModuleCategory.values()) {
            final ModuleCategory chosen = cat;
            int i = cat.ordinal();
            hit(tabX[i], panelY + 22, tabW[i], 14, () -> {
                category = chosen;
                settingsFor = null;
                rebuild();
            });
        }
        hit(closeRect[0], closeRect[1], closeRect[2], closeRect[3], this::onClose);
        if (settingsFor == null) {
            hit(actionRect[0], actionRect[1], actionRect[2], actionRect[3],
                    this::onClose);
            for (Card card : cards) {
                final Module module = card.module;
                hit(card.x, card.y, card.w, card.h, () -> {
                    module.setEnabled(!module.isEnabled());
                    Modules.get().save();
                    rebuild();
                });
            }
        } else {
            hit(actionRect[0], actionRect[1], actionRect[2], actionRect[3], () -> {
                settingsFor = null;
                rebuild();
            });
            int y = panelY + 52;
            for (String key : settingsFor.settingKeys()) {
                final String settingKey = key;
                hit(panelX + panelW - 92, y, 16, 12, () -> bump(settingKey, -1));
                hit(panelX + panelW - 72, y, 16, 12, () -> bump(settingKey, 1));
                y += 14;
            }
        }
    }

    /** Modules passing the category tab. */
    private List<Module> visible() {
        List<Module> out = new ArrayList<>();
        for (Module module : modules) {
            if (category.matches(module.category())) {
                out.add(module);
            }
        }
        return out;
    }

    private void hit(int x, int y, int w, int h, Runnable action) {
        addRenderableWidget(Button
                .builder(Component.empty(), b -> action.run())
                .bounds(x, y, w, h)
                .build());
    }

    private void bump(String key, int delta) {
        Module module = settingsFor;
        if (module == null) {
            return;
        }
        if (module.isBoolSetting(key)) {
            module.setBoolValue(key, !module.boolValue(key));
        } else {
            module.setIntValue(key, module.intValue(key) + delta * 5);
        }
        // A setting only reaches the game while the module is on, so re-apply
        // rather than making the player toggle it off and on again.
        if (module.isEnabled()) {
            module.setEnabled(false);
            module.setEnabled(true);
        }
        Modules.get().save();
        rebuild();
    }

    /** Rebuilds layout and widgets, the way a resize would. */
    private void rebuild() {
        this.clearWidgets();
        init();
    }

    /** Modules passing the category tab. */

    // ---- painting --------------------------------------------------------

    /** Paints the whole menu. Called from the per-bracket render hook. */
    public void drawOverlay(MenuPaint paint, int mouseX, int mouseY) {
        Font font = this.font;
        paint.fill(0, 0, this.width, this.height, MenuPainter.PAGE_DIM);
        MenuPainter.roundRect(paint, panelX, panelY, panelW, panelH, MenuPainter.PANEL);
        MenuPainter.outline(paint, panelX, panelY, panelW, panelH, MenuPainter.PANEL_EDGE);

        MenuPainter.text(paint, font, "CUBEON", panelX + 10, panelY + 8, MenuPainter.TEXT);
        String clock = Modules.get().clock().line();
        MenuPainter.text(paint, font, clock, (this.width - MenuPainter.w(font, clock)) / 2,
                panelY + 8, MenuPainter.TEXT_DIM);

        if (settingsFor != null) {
            MenuPainter.text(paint, font, MenuPainter.clip(font, settingsTitle, panelW - 24),
                    panelX + 12, panelY + 32, MenuPainter.TEXT);
            int sy = panelY + 52;
            for (String label : settingLabels) {
                MenuPainter.text(paint, font, MenuPainter.clip(font, label, panelW - 110),
                        panelX + 16, sy, MenuPainter.TEXT_DIM);
                sy += 14;
            }
            drawChrome(paint, font, "Back");
            return;
        }

        for (ModuleCategory cat : ModuleCategory.values()) {
            int i = cat.ordinal();
            boolean on = cat == category;
            MenuPainter.roundRect(paint, tabX[i], panelY + 22, tabW[i], 14,
                    on ? MenuPainter.TAB_ON : MenuPainter.TAB_OFF);
            String label = cat.label();
            MenuPainter.text(paint, font, label, tabX[i] + (tabW[i] - MenuPainter.w(font, label)) / 2,
                    panelY + 25, on ? MenuPainter.TEXT : MenuPainter.TEXT_DIM);
        }

        for (Card card : cards) {
            boolean hover = card.contains(mouseX, mouseY);
            MenuPainter.roundRect(paint, card.x, card.y, card.w, card.h,
                    hover ? MenuPainter.CARD_HOVER : MenuPainter.CARD);
            MenuPainter.outline(paint, card.x, card.y, card.w, card.h,
                    hover ? MenuPainter.TAB_ON : MenuPainter.CARD_EDGE);
            Module m = card.module;
            MenuPainter.text(paint, font, MenuPainter.clip(font, m.name(), card.w - 12),
                    card.x + 6, card.y + 4, MenuPainter.TEXT);
            MenuPainter.text(paint, font, MenuPainter.clip(font, m.description(), card.w - 12),
                    card.x + 6, card.y + 14, MenuPainter.TEXT_FAINT);
            // The status bar sits INSIDE the card. The first version put the
            // toggle to the right of the card, which read as three unrelated
            // columns rather than one card with a state.
            int barX = card.x + 5;
            int barY = card.y + card.h - 10;
            MenuPainter.roundRect(paint, barX, barY, 44, 9,
                    m.isEnabled() ? MenuPainter.ON_BAR : MenuPainter.OFF_BAR);
            String state = m.isEnabled() ? "Enabled" : "Disabled";
            MenuPainter.text(paint, font, state, barX + (44 - MenuPainter.w(font, state)) / 2, barY + 1,
                    m.isEnabled() ? MenuPainter.ON_TEXT : MenuPainter.OFF_TEXT);
        }

        drawChrome(paint, font, "Done");
    }

    private void drawChrome(MenuPaint paint, Font font, String label) {
        MenuPainter.roundRect(paint, closeRect[0], closeRect[1], closeRect[2],
                closeRect[3], MenuPainter.CLOSE);
        MenuPainter.text(paint, font, "X", closeRect[0] + 5, closeRect[1] + 3, MenuPainter.TEXT);
        MenuPainter.roundRect(paint, actionRect[0], actionRect[1], actionRect[2],
                actionRect[3], MenuPainter.TAB_OFF);
        MenuPainter.text(paint, font, label,
                actionRect[0] + (actionRect[2] - MenuPainter.w(font, label)) / 2,
                actionRect[1] + 3, MenuPainter.TEXT);
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
