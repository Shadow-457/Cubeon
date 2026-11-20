package com.cubeon.forge;

import com.cubeon.client.Bridge;
import com.cubeon.client.Json;
import com.cubeon.client.ui.ClientUi;
import com.cubeon.client.ui.FriendsPanel;
import com.cubeon.client.ui.MenuUi;
import net.minecraft.client.gui.GuiScreen;
import net.minecraft.client.gui.GuiTextField;
import net.minecraft.client.renderer.GlStateManager;
import org.lwjgl.input.Keyboard;
import org.lwjgl.input.Mouse;

import java.util.List;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

/**
 * 1.8.9 friends and chat screen painted by the shared {@link FriendsPanel}:
 * the rail, conversation bubbles, drafts and composer match the Fabric client.
 * Adding by ID and removing a friend stay available through the rail field and
 * a right click on a friend row.
 */
public final class FriendsScreen extends GuiScreen {
    private static final ThreadPoolExecutor ACTIONS = new ThreadPoolExecutor(1, 1, 10L, TimeUnit.SECONDS,
            new ArrayBlockingQueue<Runnable>(8), job -> {
                Thread thread = new Thread(job, "cubeon-forge-actions");
                thread.setDaemon(true);
                return thread;
            });
    static { ACTIONS.allowCoreThreadTimeOut(true); }

    private final GuiScreen parent;
    private final FriendsPanel panel = new FriendsPanel(Bridge.get());
    private GuiTextField composer, addField;
    private Bridge.Friend removing;
    private volatile String status = "";
    private volatile boolean busy;

    public FriendsScreen(GuiScreen parent) { this.parent = parent; }

    private int panelWidth() { return Math.min(width - 32, Math.min(660, Math.max(288, Math.round(width * .84F)))); }
    private int panelHeight() { return Math.min(height - 24, Math.min(380, Math.max(216, Math.round(height * .84F)))); }
    private int panelX() { return (width - panelWidth()) / 2; }
    private int panelY() { return (height - panelHeight()) / 2; }
    private int railWidth() { return Math.max(88, Math.min(156, panelWidth() / 4)); }
    private int addX() { return panelX() + 8; }
    private int addY() { return panelY() + 40; }
    private int addWidth() { return railWidth() - 16; }

    @Override public void initGui() {
        String draft = composer == null ? null : composer.getText();
        panel.ensurePeer();
        composer = new GuiTextField(901, fontRendererObj, panel.inputX(), panel.inputY(), panel.inputWidth(), 18);
        composer.setMaxStringLength(1000);
        composer.setText(draft == null ? panel.draft() : draft);
        composer.setFocused(true);
        // The shared panels draw these fields; vanilla's own box would cover them.
        composer.setEnableBackgroundDrawing(false);
        addField = new GuiTextField(902, fontRendererObj, addX() + 6, addY() + 5, addWidth() - 12, 10);
        addField.setMaxStringLength(32);
        addField.setEnableBackgroundDrawing(false);
    }

    @Override public boolean doesGuiPauseGame() { return false; }

    @Override public void updateScreen() {
        composer.updateCursorCounter();
        addField.updateCursorCounter();
        panel.saveDraft(composer.getText());
        // Clear the composer only once the relay confirms this exact text.
        if (panel.completed(composer.getText())) composer.setText("");
    }

    @Override public void drawScreen(int mouseX, int mouseY, float partial) {
        drawDefaultBackground();
        ClientUi.Canvas ui = new ForgeCanvas();
        panel.render(ui, width, height, mouseX, mouseY);

        // Compact "add by ID" field in the friend rail, styled like the shared panels.
        boolean addHover = inside(mouseX, mouseY, addX(), addY(), addWidth(), 18);
        MenuUi.pixelPanel(ui, addX(), addY(), addWidth(), 18, 6, MenuUi.SURFACE_HI,
                addField.isFocused() ? MenuUi.ACCENT : addHover ? MenuUi.BORDER_HI : MenuUi.BORDER, 1);
        addField.drawTextBox();
        composer.drawTextBox();
        if (addField.getText().isEmpty() && !addField.isFocused())
            ClientUi.left(ui, ClientUi.fit(ui, "Add by ID", addWidth() - 12),
                    addX() + 6, addY() + 5, MenuUi.FAINT);
        if (!status.isEmpty())
            ClientUi.left(ui, ClientUi.fit(ui, status, panel.inputWidth()),
                    panel.inputX(), panel.inputY() - 12, busy ? MenuUi.DIM : MenuUi.ACCENT_HI);
        if (removing != null) drawRemoveConfirm(ui, mouseX, mouseY);
        GlStateManager.color(1.0F, 1.0F, 1.0F, 1.0F);
    }

    private int confirmX() { return width / 2 - 120; }
    private int confirmY() { return height / 2 - 46; }

    private void drawRemoveConfirm(ClientUi.Canvas ui, int mouseX, int mouseY) {
        MenuUi.pixelPanel(ui, confirmX(), confirmY(), 240, 92, 10, MenuUi.SURFACE, MenuUi.BORDER_HI, 1);
        ui.text(ClientUi.fit(ui, "Remove " + removing.displayName() + "?", 216), width / 2,
                confirmY() + 14, MenuUi.TEXT);
        MenuUi.pixelButton(ui, confirmX() + 12, confirmY() + 54, 100, 24, "Remove",
                inside(mouseX, mouseY, confirmX() + 12, confirmY() + 54, 100, 24) ? 1 : 0, true, 1);
        MenuUi.pixelButton(ui, confirmX() + 128, confirmY() + 54, 100, 24, "Cancel",
                inside(mouseX, mouseY, confirmX() + 128, confirmY() + 54, 100, 24) ? 1 : 0, false, 1);
    }

    private static boolean inside(int x, int y, int left, int top, int w, int h) {
        return x >= left && x < left + w && y >= top && y < top + h;
    }

    @Override protected void mouseClicked(int mouseX, int mouseY, int button) {
        if (removing != null) {
            if (inside(mouseX, mouseY, confirmX() + 12, confirmY() + 54, 100, 24)) {
                remove(removing); removing = null;
            } else if (inside(mouseX, mouseY, confirmX() + 128, confirmY() + 54, 100, 24)
                    || button == 1 || !inside(mouseX, mouseY, confirmX(), confirmY(), 240, 92)) {
                removing = null;
            }
            return;
        }
        if (inside(mouseX, mouseY, addX(), addY(), addWidth(), 18)) {
            addField.setFocused(true); composer.setFocused(false);
            addField.mouseClicked(mouseX, mouseY, button);
            return;
        }
        addField.setFocused(false);
        int hit = panel.hit(mouseX, mouseY);
        if (hit == FriendsPanel.CLOSE) { close(); return; }
        if (hit == FriendsPanel.SEND) { send(); return; }
        List<Bridge.Friend> friends = Bridge.get().snapshot().friends();
        if (hit >= 0 && hit < friends.size()) {
            if (button == 1) removing = friends.get(hit); else panel.select(hit);
            return;
        }
        composer.setFocused(true);
        composer.mouseClicked(mouseX, mouseY, button);
    }

    @Override public void handleMouseInput() {
        super.handleMouseInput();
        int wheel = Mouse.getEventDWheel();
        if (wheel != 0) panel.scroll(Mouse.getEventX() * width / mc.displayWidth, wheel > 0 ? -1 : 1);
    }

    @Override protected void keyTyped(char typed, int key) {
        if (key == Keyboard.KEY_ESCAPE) {
            if (removing != null) { removing = null; return; }
            close(); return;
        }
        if (addField.isFocused()) {
            if (key == Keyboard.KEY_RETURN || key == Keyboard.KEY_NUMPADENTER) { add(); return; }
            addField.textboxKeyTyped(typed, key);
            return;
        }
        if (key == Keyboard.KEY_RETURN || key == Keyboard.KEY_NUMPADENTER) { send(); return; }
        if (key == Keyboard.KEY_TAB || key == Keyboard.KEY_DOWN) { panel.step(1); return; }
        if (key == Keyboard.KEY_UP) { panel.step(-1); return; }
        if (!composer.textboxKeyTyped(typed, key)) super.keyTyped(typed, key);
    }

    private void send() {
        if (composer.getText().trim().isEmpty()) return;
        panel.send(composer.getText());
        status = "";
    }

    private void add() {
        String name = addField.getText().trim();
        if (name.isEmpty()) return;
        act("/add", Json.object("name", name));
        addField.setText("");
        addField.setFocused(false);
    }

    private void remove(Bridge.Friend friend) {
        act("/remove", Json.object("name", friend.name()));
    }

    private void act(String path, String body) {
        if (busy) { status = "Please wait for the current action."; return; }
        busy = true;
        status = "Working…";
        try {
            ACTIONS.execute(() -> {
                try {
                    Bridge.Result result = Bridge.get().post(path, body);
                    status = result.ok() ? "Done" : result.error();
                    Bridge.get().wake();
                } finally {
                    busy = false;
                }
            });
        } catch (RejectedExecutionException e) {
            busy = false;
            status = "Please wait for the current action.";
        }
    }

    @Override public void onGuiClosed() { panel.close(); }

    private void close() { mc.displayGuiScreen(parent); }
}
