package com.cubeon.client;

import com.cubeon.client.Bridge.ChatConversation;
import com.cubeon.client.Bridge.ChatMessage;
import com.cubeon.client.Bridge.Friend;
import com.cubeon.client.Bridge.Result;
import com.cubeon.client.Bridge.Snapshot;
import com.cubeon.client.Bridge.Toast;

import net.minecraft.ChatFormatting;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.components.AbstractWidget;
import net.minecraft.client.gui.components.Button;
import net.minecraft.client.gui.components.EditBox;
import net.minecraft.client.gui.components.StringWidget;
import net.minecraft.client.gui.components.Tooltip;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.network.chat.Component;
import net.minecraft.network.chat.MutableComponent;

import java.util.ArrayList;
import java.util.List;
import java.util.function.Consumer;
import java.util.function.Supplier;

/**
 * The in-game Cubeon chat: the launcher's Chat tab, reachable from inside
 * Minecraft. Every other friend-management job - adding friends, answering
 * requests, world invites, mod sync, whitelisting - lives in the launcher and
 * only there; this screen is the conversation surface and nothing else.
 *
 * <p>Two views share one frame: the friends picker (a row per friend, online
 * presence shown) and, once a friend is chosen, the transcript with a composer
 * underneath. Both read the same chat store the launcher's Chat tab does - the
 * messages are decrypted by the launcher and polled over the localhost bridge
 * ({@code /chat}), and a send is a {@code /dm} POST - so the two always show
 * the same conversation, live.
 *
 * <h2>Why this screen is built out of nothing but widgets</h2>
 *
 * This is the one Minecraft-facing file in the mod, and it is written to the
 * smallest slice of the game's API that has survived every version Cubeon can
 * launch. That slice is: {@code Screen}'s lifecycle ({@code init}, {@code tick},
 * {@code removed}, {@code onClose}), {@code addRenderableWidget}, and the three
 * widgets {@code Button}, {@code EditBox} and {@code StringWidget}. Nothing else.
 *
 * <p>In particular this screen never overrides {@code render},
 * {@code mouseClicked}, {@code mouseScrolled} or {@code keyPressed}, and never
 * mentions a graphics class. Those are exactly the members Minecraft reshaped
 * between eras: drawing moved from {@code GuiGraphics} to a render-state
 * extractor, {@code keyPressed(int, int, int)} became
 * {@code keyPressed(KeyEvent)}, {@code mouseClicked(double, double, int)} became
 * {@code mouseClicked(MouseButtonEvent, boolean)}, and {@code mouseScrolled}
 * gained an axis. An override whose signature no longer exists silently stops
 * being an override - the screen still compiles, still runs, and simply never
 * draws or never responds - which is the worst possible failure mode. Widgets
 * have none of that history: the framework renders them and routes clicks to
 * them, so letting it do both is what makes one source tree correct on all of
 * them.
 *
 * <p>Three features are given up for that, deliberately: the list scrolls by
 * page buttons rather than the mouse wheel (the wheel needs
 * {@code mouseScrolled}), Enter does not submit the message box (that needs
 * {@code keyPressed}), and there is no scroll-back beyond what fits the
 * transcript pool. Each has a visible button doing the same job where it can.
 *
 * <h2>The other rules this screen follows</h2>
 *
 * <ul>
 * <li><b>No network call on the render thread.</b> Everything reads
 *     {@link Bridge#snapshot()} and {@link Bridge#chat()}, which never block,
 *     and the Send button posts from a worker thread.
 * <li><b>Widgets are created in {@code init()} and afterwards only mutated.</b>
 *     An earlier version of this screen appended rows into a layout it never
 *     cleared, so every reopen and every window resize added another copy of
 *     every row. The widget set here is fixed and sized to the window; a
 *     changing roster changes labels, not the widget list.
 * <li><b>Only the main thread touches screen state.</b> Workers hand results
 *     back through {@link Minecraft#execute} and check the screen is still open
 *     before using them.
 * </ul>
 */
public class CubeonClientScreen extends Screen {

    // ---- geometry --------------------------------------------------------
    // Minecraft guarantees a scaled GUI of at least 320x240, so every size here
    // is picked to still fit - and still be usable - at exactly that.

    private static final int PANEL_MAX_W = 340;
    private static final int GAP = 4;
    private static final int BTN_H = 20;
    private static final int LINE_H = 10;

    private static final int TITLE_Y = 8;
    private static final int HEADER_Y = 20;

    private static final int ROW_STEP = BTN_H + 2;
    /** Row buttons that exist; how many are shown depends on the window. */
    private static final int ROW_SLOTS = 8;
    /** Lines of prose the empty states use. */
    private static final int INFO_LINES = 6;
    /** Transcript prose step and pool: taller than the row list because prose
     * wraps, but capped so a long conversation can't grow the widget set. */
    private static final int CHAT_LINE_STEP = LINE_H + 2;
    private static final int CHAT_POOL = 24;
    /** The longest message the composer accepts, before the launcher's cap. */
    private static final int CHAT_INPUT_MAX = 1000;

    private static final int PRIMARY_BTN_W = 80;
    private static final int DONE_W = 100;

    /** How long a status message stays up: 10 seconds at 20 ticks a second. */
    private static final int STATUS_TICKS = 200;

    /** One list entry. Rows are data; the row buttons are recycled. */
    private record Row(String name, String label, String sub, ChatFormatting color) {}

    /**
     * A button whose job changes with the view and the selection. Reassigning a
     * label and an action is how this screen adapts without ever creating or
     * destroying a widget after {@code init()}.
     */
    private static final class Slot {
        Button button;
        Runnable action;
    }

    /**
     * One line of text, plus where it wants to sit.
     *
     * <p>{@code StringWidget} is the one widget whose behaviour genuinely differs
     * between the versions this mod targets: 1.20.1 centres its text inside its
     * box, later versions grew {@code alignLeft}/{@code alignRight} (which 26.x
     * dropped again), and the newer ones scroll text that does not fit. Sizing the
     * widget to the exact width of its own text settles all three - centred, left
     * and right land in the same place, and nothing is ever wide enough to need
     * scrolling. That is why a label carries its box here and the widget is
     * resized every time the text changes.
     */
    private static final class Label {
        StringWidget widget;
        Component text = Component.empty();
        int x;
        int y;
        int box;
        boolean centered;
    }

    // ---- state -----------------------------------------------------------

    private final Screen parent;
    private final Bridge bridge = Bridge.get();
    /** Stable identity lets Bridge remove only this screen's callback on close. */
    private final Consumer<Toast> screenNoticeSink = this::onNotice;

    private final Slot[] rowSlots = new Slot[ROW_SLOTS];
    /** The picker's footer button: Chat, opening the selected conversation. */
    private final Slot primary = new Slot();
    private final Slot prevPage = new Slot();
    private final Slot nextPage = new Slot();
    /** The transcript's one button: Close, back to the picker. */
    private final Slot chatClose = new Slot();
    private final Label[] info = new Label[INFO_LINES];
    private final Label[] chatLines = new Label[CHAT_POOL];

    private Label titleLine;
    private Label headerLine;
    private Label pageLine;
    private Label statusLine;
    private EditBox input;

    /**
     * The selected row, held by name rather than by index on purpose: the roster
     * re-sorts whenever somebody comes online, and an index would then quietly
     * point at a different person than the one that was highlighted.
     */
    private String selected = "";

    private List<Row> rows = List.of();

    /** True while this screen is showing a transcript (a friend is chosen). */
    private boolean chatOpen;

    /** How many row buttons this window has room for. Set by {@link #layout}. */
    private int visibleRows = 1;
    /** How many transcript prose lines fit. Set by layout(). */
    private int transcriptRows = 1;
    /** The y below which the list region ends (above the pager). Set by layout(). */
    private int listBottom;
    private int page;

    /**
     * What the player has typed. Kept outside the widget because a window
     * resize rebuilds every widget, and losing a half-typed message to a resize
     * is exactly the kind of small bug that makes a UI feel broken.
     */
    private String draft = "";

    private String status = "";
    private boolean statusIsError;
    private int statusTicks;
    /**
     * A status the launcher's own notices must not overwrite.
     *
     * <p>A confirmation the player asked for outranks a background toast; an
     * error still gets through, because a sticky success must never hide a real
     * failure.
     */
    private boolean statusSticky;

    /** True while a launcher call is in flight. Main thread only. */
    private boolean busy;

    private boolean viewerReleased;

    // Change detection, so labels are rebuilt on real change instead of every
    // tick. Snapshot and ChatConversation compare by value, which is what makes
    // this reliable.
    private long seenRevision = -1;
    private long seenChatRevision = -1;
    private boolean seenChatOpen;
    private String seenSelected = " ";
    private boolean seenBusy;

    // Resolved by layout(); read when rows are laid out and paged.
    private int panelX;
    private int panelW;
    private int listTop;

    public CubeonClientScreen(Screen parent) {
        super(Component.literal("Cubeon Chat"));
        this.parent = parent;
        bridge.start();          // idempotent; the client initializer normally did it
        bridge.addViewer();      // paired with removed(); the constructor runs once
    }

    /** Size of the chat corner icon, and its inset from the screen edge. */
    public static final int ICON_W = 20;
    public static final int ICON_H = 20;
    public static final int ICON_INSET = 4;

    /**
     * The small chat corner icon both the pause-menu and title-screen mixins
     * drop into Minecraft's own menus, docked top-left. The two mixins share
     * one size and one open action through this factory.
     *
     * @param parent the menu screen to come back to when this screen closes
     */
    public static Button menuButton(Screen parent) {
        return Button
                .builder(iconLabel(), button -> Minecraft.getInstance().setScreen(
                        new CubeonClientScreen(parent)))
                .bounds(0, 0, ICON_W, ICON_H)
                .tooltip(Tooltip.create(Component.literal(
                        "Cubeon Chat - message your friends")))
                .build();
    }

    /**
     * The label on the corner icon. The 1.20-1.21 bracket renders a blank square
     * and the 26 bracket the two-person glyph; neither carries a count, because
     * unread tracking lives in the launcher's Chat tab, not here.
     */
    private static Component iconLabel() {
        return CornerIcon.label(0);
    }

    // ---- setup -----------------------------------------------------------

    @Override
    protected void init() {
        // Notices arriving while this screen is up are shown in its own status
        // line instead of the hotbar overlay, which needs a live player and is
        // invisible from a menu. init() runs on resize too; re-setting the same
        // sink is harmless.
        bridge.setScreenToastSink(screenNoticeSink);

        titleLine = line(this.title);
        headerLine = line(Component.empty());

        // The prose lines come before the row buttons so that a row button is
        // never drawn underneath a line of text: only one of the two sets is
        // ever visible at a time, but insertion order is render order and
        // relying on that is free.
        for (int i = 0; i < info.length; i++) {
            info[i] = line(Component.empty());
        }
        for (int i = 0; i < rowSlots.length; i++) {
            Slot slot = new Slot();
            slot.button = add(slotButton(slot));
            rowSlots[i] = slot;
        }

        // The transcript prose pool. Created with the rows but never shown at
        // the same time as them: a transcript replaces the friend picker, it
        // doesn't join it.
        for (int i = 0; i < chatLines.length; i++) {
            chatLines[i] = line(Component.empty());
        }
        chatClose.button = add(slotButton(chatClose));

        prevPage.button = add(slotButton(prevPage));
        nextPage.button = add(slotButton(nextPage));
        pageLine = line(Component.empty());

        input = new EditBox(this.font, 0, 0, 40, BTN_H, Component.literal("Message"));
        input.setMaxLength(CHAT_INPUT_MAX);
        input.setValue(draft);
        input.setResponder(value -> draft = value);
        add(input);
        primary.button = add(slotButton(primary));

        statusLine = line(Component.empty());
        add(Button.builder(Component.literal("Done"), b -> onClose())
                .bounds((this.width - DONE_W) / 2, this.height - 24, DONE_W, BTN_H)
                .build());

        layout();
        // Force a full label pass: init() may be a resize, in which case the
        // snapshot has not changed and tick() would otherwise skip it.
        seenRevision = -1;
        seenChatRevision = -1;
        apply(bridge.snapshot());
    }

    private Label line(Component message) {
        Label label = new Label();
        label.text = message;
        label.widget = add(new StringWidget(0, 0, 10, LINE_H, message, this.font));
        return label;
    }

    private Button slotButton(Slot slot) {
        return Button.builder(Component.empty(), b -> {
            if (slot.action != null) {
                slot.action.run();
            }
        }).bounds(0, 0, 40, BTN_H).build();
    }

    private <T extends AbstractWidget> T add(T widget) {
        addRenderableWidget(widget);
        return widget;
    }

    /**
     * Places every widget and works out how many rows fit. Runs on init, and
     * again whenever anything resizes the window.
     */
    private void layout() {
        panelW = Math.min(PANEL_MAX_W, this.width - 2 * GAP);
        panelX = (this.width - panelW) / 2;

        place(titleLine, panelX, TITLE_Y, panelW, true);
        place(headerLine, panelX, HEADER_Y, panelW);

        listTop = HEADER_Y + LINE_H + GAP;

        // Bottom-up: the chrome is fixed, and whatever vertical space is left
        // over becomes rows. One row always survives, however short the window.
        int pagerY = this.height - 102;
        int closeY = this.height - 78;
        int footerY = this.height - 54;
        int statusY = this.height - 34;

        int room = pagerY - GAP - listTop;
        visibleRows = Math.max(1, Math.min(ROW_SLOTS, room / ROW_STEP));
        transcriptRows = Math.max(1, Math.min(CHAT_POOL, room / CHAT_LINE_STEP));
        listBottom = pagerY - GAP;

        for (int i = 0; i < rowSlots.length; i++) {
            Button button = rowSlots[i].button;
            button.setWidth(panelW);
            button.setX(panelX);
            button.setY(listTop + i * ROW_STEP);
        }
        for (int i = 0; i < info.length; i++) {
            place(info[i], panelX, listTop + 4 + i * (LINE_H + 2), panelW);
        }

        int pageBtnW = 60;
        prevPage.button.setWidth(pageBtnW);
        prevPage.button.setX(panelX);
        prevPage.button.setY(pagerY);
        nextPage.button.setWidth(pageBtnW);
        nextPage.button.setX(panelX + panelW - pageBtnW);
        nextPage.button.setY(pagerY);
        place(pageLine, panelX + pageBtnW + GAP, pagerY + 5,
                Math.max(10, panelW - 2 * (pageBtnW + GAP)), true);

        // The transcript's one action - Close, back to the picker - takes the
        // whole action line alone, centred.
        chatClose.button.setWidth(panelW / 2);
        chatClose.button.setX(panelX + (panelW - chatClose.button.getWidth()) / 2);
        chatClose.button.setY(closeY);

        input.setWidth(panelW - PRIMARY_BTN_W - GAP);
        input.setX(panelX);
        input.setY(footerY);
        primary.button.setWidth(PRIMARY_BTN_W);
        primary.button.setX(panelX + panelW - PRIMARY_BTN_W);
        primary.button.setY(footerY);

        place(statusLine, panelX, statusY, panelW);
        clampPage();
    }

    private void place(Label label, int x, int y, int box) {
        place(label, x, y, box, false);
    }

    private void place(Label label, int x, int y, int box, boolean centered) {
        label.x = x;
        label.y = y;
        label.box = Math.max(1, box);
        label.centered = centered;
        fit(label);
    }

    /** Sets a label's text, resizing it so its alignment cannot matter. */
    private void say(Label label, Component message) {
        label.text = message;
        fit(label);
    }

    private void show(Label label, boolean visible) {
        label.widget.visible = visible;
    }

    private void fit(Label label) {
        // +1 so a rounding difference in the game's own text measurement can
        // never clip the last pixel column of a glyph.
        int width = Math.min(label.box, this.font.width(label.text.getString()) + 1);
        width = Math.max(1, width);
        label.widget.setWidth(width);
        label.widget.setX(label.centered ? label.x + (label.box - width) / 2 : label.x);
        label.widget.setY(label.y);
    }

    // ---- per-tick state --------------------------------------------------

    @Override
    public void tick() {
        if (statusTicks > 0 && --statusTicks == 0) {
            status = "";
            statusSticky = false;
            seenRevision = -1;   // force the status line to be cleared
        }
        long revision = bridge.revision();
        long chatRevision = bridge.chatRevision();
        boolean open = isChatOpen();
        if (revision != seenRevision || chatRevision != seenChatRevision
                || open != seenChatOpen || !selected.equals(seenSelected)
                || busy != seenBusy) {
            seenRevision = revision;
            seenChatRevision = chatRevision;
            seenChatOpen = open;
            seenSelected = selected;
            seenBusy = busy;
            apply(bridge.snapshot());
        }
    }

    /** True while the bridge has a conversation open for this screen. */
    private boolean isChatOpen() {
        return !bridge.chatFriend().isEmpty();
    }

    /** Rebuilds the rows and every mutable label from one snapshot. */
    private void apply(Snapshot snap) {
        // The conversation belongs to the picker's selection: if the selected
        // friend goes away (removed you, roster refresh), the conversation
        // closes with them rather than showing a stranger's empty room.
        chatOpen = isChatOpen();
        if (chatOpen && find(snap, bridge.chatFriend()) == null) {
            bridge.setChatFriend("");
            chatOpen = false;
            selected = "";
        }
        rows = buildRows(snap);

        // Drop a selection that no longer exists.
        if (!chatOpen) {
            boolean stillThere = false;
            for (Row row : rows) {
                if (row.name().equals(selected)) {
                    stillThere = true;
                    break;
                }
            }
            if (!stillThere) {
                selected = "";
            }
        }
        clampPage();

        say(headerLine, colored(trim(snap.connectionLine(), panelW), headerColor(snap)));

        applyRows();
        applyInfo(snap);
        applyChat();
        applyChatClose();
        applyFooter(snap);
    }

    private List<Row> buildRows(Snapshot snap) {
        List<Row> out = new ArrayList<>();
        if (chatOpen) {
            return out;   // a transcript replaces the picker, it doesn't join it
        }
        for (Friend friend : snap.friends()) {
            ChatFormatting color = friend.online()
                    ? ChatFormatting.WHITE : ChatFormatting.GRAY;
            out.add(new Row(friend.name(), friend.label(), friend.presence(), color));
        }
        return out;
    }

    /**
     * Points the row buttons at the current page. A slot past the end of the
     * list, or past what the window has room for, is hidden rather than left
     * showing a stale name.
     */
    private void applyRows() {
        boolean picker = !chatOpen;
        int first = page * visibleRows;
        for (int i = 0; i < rowSlots.length; i++) {
            Slot slot = rowSlots[i];
            int index = first + i;
            boolean used = picker && i < visibleRows && index < rows.size();
            slot.button.visible = used;
            slot.button.active = used;
            slot.action = null;
            slot.button.setTooltip(null);
            if (!used) {
                continue;
            }
            Row row = rows.get(index);
            boolean isSelected = row.name().equals(selected);
            String label = (isSelected ? "> " : "") + row.label() + " - " + row.sub();
            slot.button.setMessage(colored(trim(label, panelW - 8), row.color()));
            slot.button.setTooltip(Tooltip.create(Component.literal(
                    isSelected ? "Click again to chat with " + row.label()
                            : "Select " + row.label())));
            String name = row.name();
            slot.action = () -> onRowClicked(name);
        }

        int pages = pageCount();
        boolean paged = picker && pages > 1;
        prevPage.button.visible = paged;
        nextPage.button.visible = paged;
        show(pageLine, paged);
        prevPage.button.active = paged && page > 0;
        nextPage.button.active = paged && page < pages - 1;
        if (paged) {
            prevPage.button.setMessage(Component.literal("< Back"));
            nextPage.button.setMessage(Component.literal("More >"));
            say(pageLine, Component.literal("Page " + (page + 1) + "/" + pages));
            prevPage.action = () -> turnPage(-1);
            nextPage.action = () -> turnPage(1);
        }
    }

    /**
     * A click on a row selects it; a click on the row that is already selected
     * opens the conversation. That is the mouse-wheel-free stand-in for the
     * double click a drawn list would have had.
     */
    private void onRowClicked(String name) {
        if (!name.equals(selected)) {
            selected = name;
            apply(bridge.snapshot());   // the footer must reflect the new row now
            return;
        }
        openChat(name);
    }

    /** Opens the conversation for one friend (no network - the bridge polls it). */
    private void openChat(String name) {
        bridge.setChatFriend(name);
        selected = name;
        page = 0;
        setStatus("", false);
        apply(bridge.snapshot());
    }

    /** Closes the open conversation and returns to the picker. */
    private void closeChat() {
        bridge.setChatFriend("");
        selected = "";
        page = 0;
        setStatus("", false);
        apply(bridge.snapshot());
    }

    private void turnPage(int step) {
        page += step;
        clampPage();
        apply(bridge.snapshot());
    }

    private int pageCount() {
        return Math.max(1, (rows.size() + visibleRows - 1) / visibleRows);
    }

    private void clampPage() {
        page = Math.max(0, Math.min(page, pageCount() - 1));
    }

    /* The prose block: every empty list, and nothing while the transcript owns
     * the region. */
    private void applyInfo(Snapshot snap) {
        List<Component> lines = new ArrayList<>();
        if (chatOpen) {
            // The transcript owns the whole list region; nothing else belongs
            // here. Build nothing, show nothing.
        } else if (rows.isEmpty()) {
            lines.add(colored(emptyHead(snap), ChatFormatting.WHITE));
            for (String line : wrap(emptyBody(snap), panelW - 8)) {
                lines.add(colored(line, ChatFormatting.GRAY));
            }
        }
        for (int i = 0; i < info.length; i++) {
            boolean used = i < lines.size();
            show(info[i], used);
            if (used) {
                say(info[i], lines.get(i));
            }
        }
    }

    private String emptyHead(Snapshot snap) {
        if (!snap.launcherUp()) {
            return "Cubeon launcher not running";
        }
        if (!snap.claimed()) {
            return "No Cubeon name yet";
        }
        return "No friends to message yet";
    }

    private String emptyBody(Snapshot snap) {
        if (!snap.launcherUp()) {
            return snap.problem().isEmpty()
                    ? "Start Cubeon and this screen fills in by itself." : snap.problem();
        }
        if (!snap.claimed()) {
            return "Open the Cubeon launcher once to finish setting up.";
        }
        return "Add friends from the Cubeon launcher's Chat tab - by their Cubeon "
                + "ID - and they appear here.";
    }

    /**
     * The transcript: the read-only prose that fills the list region while a
     * conversation is open, newest anchored at the bottom, above the pager.
     */
    private void applyChat() {
        for (int i = 0; i < chatLines.length; i++) {
            show(chatLines[i], false);
        }
        if (!chatOpen) {
            return;
        }
        ChatConversation conversation = bridge.chat();
        List<Component> lines = chatTranscript(conversation);
        int shown = Math.min(lines.size(), transcriptRows);
        int first = lines.size() - shown;
        for (int i = 0; i < shown; i++) {
            Label label = chatLines[i];
            // Newest anchored to the bottom of the region, above the pager.
            place(label, panelX + 4, listBottom - LINE_H - (shown - 1 - i) * CHAT_LINE_STEP,
                    panelW - 8);
            show(label, true);
            say(label, lines.get(first + i));
        }
    }

    /** The transcript as wrapped prose lines, oldest first: incoming WHITE,
     * outgoing AQUA, so a conversation reads at a glance. */
    private List<Component> chatTranscript(ChatConversation conversation) {
        List<Component> out = new ArrayList<>();
        String friend = conversation.friend();
        if (conversation.messages().isEmpty()) {
            out.add(colored("No messages with " + friend + " yet.",
                    ChatFormatting.GRAY));
            out.add(colored("Messages here are encrypted end to end.",
                    ChatFormatting.GRAY));
            return out;
        }
        for (ChatMessage message : conversation.messages()) {
            String name = message.name();
            if (name == null || name.isEmpty()) {
                name = message.incoming() ? friend : "You";
            }
            ChatFormatting color = message.incoming()
                    ? ChatFormatting.WHITE : ChatFormatting.AQUA;
            for (String line : wrap(name + ": " + message.text(), panelW - 8)) {
                out.add(colored(line, color));
            }
        }
        return out;
    }

    private void applyChatClose() {
        chatClose.action = null;
        chatClose.button.active = false;
        chatClose.button.setTooltip(null);
        chatClose.button.visible = chatOpen;
        if (chatOpen) {
            chatClose.button.setMessage(Component.literal("Close"));
            chatClose.button.active = !busy;
            chatClose.button.setTooltip(Tooltip.create(Component.literal(
                    "Back to your friends list. The conversation stays on this "
                            + "computer.")));
            chatClose.action = this::closeChat;
        }
    }

    private void applyFooter(Snapshot snap) {
        boolean typing = false;
        primary.action = null;
        primary.button.active = false;
        primary.button.setTooltip(null);
        primary.button.visible = true;

        if (chatOpen) {
            // A conversation is open: the box composes a message and the
            // primary sends it. The picker's rows and pager are gone, so the
            // input is the whole bottom bar.
            typing = true;
            input.setMaxLength(CHAT_INPUT_MAX);
            input.setHint(Component.literal("Message " + bridge.chatFriend()));
            primary.button.setMessage(Component.literal("Send"));
            primary.action = this::submitSend;
            primary.button.active = !busy && snap.claimed();
        } else {
            // The picker: no text entry, just rows. The primary opens the
            // selected friend's conversation, matching how the row
            // double-click works.
            input.setMaxLength(CHAT_INPUT_MAX);
            primary.button.setMessage(Component.literal("Chat"));
            if (selected.isEmpty()) {
                primary.button.setTooltip(Tooltip.create(Component.literal(
                        "Pick a friend to open a conversation.")));
            } else {
                String who = selected;
                primary.button.active = !busy && snap.claimed();
                primary.button.setTooltip(Tooltip.create(Component.literal(
                        "Open your conversation with " + peerLabel(who) + ".")));
                primary.action = () -> openChat(who);
            }
        }
        primary.button.active = primary.button.active && primary.button.visible;
        input.visible = typing;
        input.setEditable(typing && !busy);

        String footnote = status;
        ChatFormatting color = statusIsError ? ChatFormatting.RED : ChatFormatting.YELLOW;
        if (footnote.isEmpty() && !chatOpen) {
            footnote = hint(snap);
            color = ChatFormatting.GRAY;
        }
        show(statusLine, !footnote.isEmpty());
        say(statusLine, colored(trim(footnote, panelW), color));
    }

    /** The one line of guidance under the list on the picker. */
    private String hint(Snapshot snap) {
        if (selected.isEmpty()) {
            return snap.friends().isEmpty() ? ""
                    : "Pick a friend, then press Chat.";
        }
        Friend friend = find(snap, selected);
        if (friend == null) {
            return "";
        }
        return friend.online()
                ? "Press Chat to message " + peerLabel(selected) + "."
                : peerLabel(selected) + " is offline - messages still arrive.";
    }

    private ChatFormatting headerColor(Snapshot snap) {
        if (!snap.launcherUp() || !snap.available()) {
            return ChatFormatting.RED;
        }
        if (!snap.claimed() || !snap.connected()) {
            return ChatFormatting.GOLD;
        }
        return ChatFormatting.GREEN;
    }

    private String peerLabel(String handle) {
        return bridge.snapshot().peer(handle).label();
    }

    private static Friend find(Snapshot snap, String name) {
        for (Friend friend : snap.friends()) {
            if (friend.name().equals(name)) {
                return friend;
            }
        }
        return null;
    }

    // ---- actions ---------------------------------------------------------

    /**
     * Runs a launcher call on a worker thread and reports back on the main one.
     *
     * <p>The {@code /dm} POST blocks on the launcher answering; calling it
     * inline would freeze the game.
     */
    private void submit(String working, String done, Supplier<Result> call) {
        submit(working, done, call, false);
    }

    /**
     * @param stickyDone keep the success line up until the player does something
     *                   else, instead of letting the next launcher notice
     *                   overwrite it.
     */
    private void submit(String working, String done, Supplier<Result> call,
                        boolean stickyDone) {
        if (busy) {
            return;
        }
        busy = true;
        setStatus(working, false);
        apply(bridge.snapshot());   // grey the buttons out immediately

        Thread worker = new Thread(() -> {
            Result result;
            try {
                result = call.get();
                if (result == null) {
                    result = Result.fail("Cubeon returned no result.");
                }
            } catch (RuntimeException ex) {
                // A worker that dies silently would leave the screen stuck on
                // "working..." with every button greyed out for good.
                result = Result.fail("Cubeon couldn't finish that: " + ex);
            }
            Result outcome = result;
            Minecraft mc = Minecraft.getInstance();
            onClientThread(mc, () -> {
                busy = false;
                if (mc.screen != this) {
                    return;   // the player has already left this screen
                }
                setStatus(outcome.ok() ? done : outcome.error(), !outcome.ok(),
                        stickyDone && outcome.ok());
                apply(bridge.snapshot());
            });
        }, "cubeon-client-action");
        worker.setDaemon(true);
        worker.start();
    }

    /**
     * Sends the composer's text to the friend whose conversation is open.
     * Local checks first: nothing leaves this machine until the message is
     * obviously sendable. The launcher echoes the stored message back, which is
     * what actually puts it on the transcript.
     */
    private void submitSend() {
        String friend = bridge.chatFriend();
        if (friend == null || friend.isEmpty()) {
            return;
        }
        String text = input.getValue();
        text = text == null ? "" : text.trim();
        if (text.isEmpty()) {
            flash("Type a message first.");
            return;
        }
        if (text.length() > CHAT_INPUT_MAX) {
            flash("That message is too long - keep it under "
                    + CHAT_INPUT_MAX + " characters.");
            return;
        }
        String to = friend;
        String message = text;
        submit("Sending to " + to + "...", "",
                () -> clearInputOnSuccess(bridge.sendChat(to, message)));
    }

    /** Runs on a worker thread, so the box is cleared back on the main one. */
    private Result clearInputOnSuccess(Result result) {
        if (result != null && result.ok()) {
            Minecraft mc = Minecraft.getInstance();
            onClientThread(mc, () -> {
                draft = "";
                if (mc.screen == this && input != null) {
                    input.setValue("");
                }
            });
        }
        return result;
    }

    /** Shows a problem the launcher never saw, without a round trip. */
    private void flash(String message) {
        setStatus(message, true);
        apply(bridge.snapshot());
    }

    /**
     * A launcher notice delivered on the bridge's poll thread while this screen
     * is open. Put it on the status line (red for errors) so a "No Cubeon user
     * named X." or a message arriving on its own is visible from a menu - the
     * overlay sink needs a live player and never draws over one of these.
     */
    private void onNotice(Toast toast) {
        if (toast == null) {
            return;
        }
        Minecraft mc = Minecraft.getInstance();
        onClientThread(mc, () -> {
            if (mc.screen != this) {
                return;   // closed between the drain and this execute
            }
            // A sticky line outranks routine news: the launcher emits its own
            // notice for the very message we just confirmed, and overwriting
            // ours would hide the confirmation. A real error still gets
            // through - it's the more useful of the two.
            if (statusSticky && !toast.error()) {
                return;
            }
            setStatus(toast.text(), toast.error());
            apply(bridge.snapshot());
        });
    }

    /** Minecraft may reject work while the client is shutting down. */
    private static void onClientThread(Minecraft mc, Runnable task) {
        if (mc == null || task == null) {
            return;
        }
        try {
            mc.execute(task);
        } catch (RuntimeException ignored) {
            // The screen is already going away; there is nothing to update.
        }
    }

    private void setStatus(String text, boolean error) {
        setStatus(text, error, false);
    }

    private void setStatus(String text, boolean error, boolean sticky) {
        status = text == null ? "" : text;
        statusIsError = error;
        statusTicks = status.isEmpty() ? 0 : STATUS_TICKS;
        statusSticky = sticky && !status.isEmpty();
    }

    // ---- text ------------------------------------------------------------
    // Hand-rolled instead of Font.split / plainSubstrByWidth: font.width() is
    // the one text measurement whose shape has never changed, and these two
    // helpers are all this screen needs.

    private static MutableComponent colored(String text, ChatFormatting color) {
        return Component.literal(text).withStyle(color);
    }

    private String trim(String text, int maxWidth) {
        if (maxWidth <= 0) {
            return "";
        }
        if (this.font.width(text) <= maxWidth) {
            return text;
        }
        int limit = maxWidth - this.font.width("...");
        if (limit <= 0) {
            return "";
        }
        StringBuilder out = new StringBuilder();
        int used = 0;
        for (int i = 0; i < text.length(); i++) {
            int charWidth = this.font.width(String.valueOf(text.charAt(i)));
            if (used + charWidth > limit) {
                break;
            }
            out.append(text.charAt(i));
            used += charWidth;
        }
        return out + "...";
    }

    private List<String> wrap(String text, int maxWidth) {
        List<String> out = new ArrayList<>();
        StringBuilder line = new StringBuilder();
        for (String word : text.split(" ")) {
            String candidate = line.length() == 0 ? word : line + " " + word;
            if (this.font.width(candidate) > maxWidth && line.length() > 0) {
                out.add(line.toString());
                line = new StringBuilder(word);
            } else {
                line.setLength(0);
                line.append(candidate);
            }
        }
        if (line.length() > 0) {
            out.add(line.toString());
        }
        return out;
    }

    // ---- lifecycle -------------------------------------------------------

    @Override
    public void removed() {
        // Guarded: a double removed() would decrement the viewer count twice and
        // slow polling down for every screen opened afterwards.
        if (!viewerReleased) {
            viewerReleased = true;
            bridge.removeViewer();
        }
        // Leaving the screen closes any open conversation, so the bridge's chat
        // poll stream goes quiet instead of following you into the world.
        bridge.setChatFriend("");
        // A notice that arrives after close goes back to the overlay sink.
        bridge.clearScreenToastSink(screenNoticeSink);
        super.removed();
    }

    @Override
    public void onClose() {
        Minecraft mc = this.minecraft;
        if (mc != null) {
            mc.setScreen(parent);   // back to the pause menu, not to the world
        } else {
            super.onClose();
        }
    }
}
