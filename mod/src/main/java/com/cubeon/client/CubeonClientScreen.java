package com.cubeon.client;

import com.cubeon.client.Bridge.Friend;
import com.cubeon.client.Bridge.Result;
import com.cubeon.client.Bridge.Session;
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
 * The in-game Friends screen: everything the launcher's Friends tab used to do,
 * done from inside Minecraft.
 *
 * <p>Three tabs share one frame - the roster, pending requests, and your
 * Cubeon account - with a session banner above them whenever a world
 * session is live. Selecting a row and acting on it from a fixed button bar is
 * how vanilla's own world and server screens work.
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
 * <p>Two features are given up for that, deliberately: the list scrolls by page
 * buttons rather than the mouse wheel (the wheel needs {@code mouseScrolled}),
 * and Enter does not submit the name box (that needs {@code keyPressed}). Both
 * have a visible button doing the same job.
 *
 * <h2>The other rules this screen follows</h2>
 *
 * <ul>
 * <li><b>No network call on the render thread.</b> Everything reads
 *     {@link Bridge#snapshot()}, which never blocks, and every button posts from
 *     a worker thread.
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
    private static final int TAB_Y = 32;
    private static final int BANNER_Y = 56;
    private static final int BANNER_H = 34;

    private static final int ROW_STEP = BTN_H + 2;
    /** Row buttons that exist; how many are shown depends on the window. */
    private static final int ROW_SLOTS = 8;
    /** Lines of prose the account tab and the empty states share. */
    private static final int INFO_LINES = 6;
    /** Prose step and pool for the Sync report: taller than the row list
     * because prose wraps, but capped so a long report can't grow the widget set. */
    private static final int SYNC_LINE_STEP = LINE_H + 2;
    private static final int SYNC_POOL = 24;

    private static final int SESSION_BTN_W = 56;
    private static final int PRIMARY_BTN_W = 80;
    private static final int DONE_W = 100;

    /** How long a status message stays up: 10 seconds at 20 ticks a second. */
    private static final int STATUS_TICKS = 200;

    private enum Tab {
        FRIENDS, REQUESTS
    }

    /** One list entry. Rows are data; the row buttons are recycled. */
    private record Row(String name, String label, String sub, ChatFormatting color) {}

    /**
     * A button whose job changes with the tab and the selection. Reassigning a
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

    /**
     * Whether the Invite action can actually do anything from where this screen
     * was opened. Inviting starts a world-session host flow that ends with
     * "open your world to LAN" - that only makes sense in a world the player
     * hosts. From the title screen, or the pause menu of a remote server, the
     * rest of the screen (roster, requests, joining, account) still works; the
     * Invite button is greyed out with an explanation instead.
     */
    private final boolean canInvite;

    private final Slot[] rowSlots = new Slot[ROW_SLOTS];
    /**
     * The action bar. Four slots, because a mutual friend's profile carries four
     * verbs: Play, Sync, Whitelist, Remove. At Minecraft's guaranteed minimum
     * 320-wide GUI that leaves 74px each, which fits every label below. The Play
     * and Sync sub-views borrow the first three slots and hide the rest.
     */
    private final Slot[] actions = {new Slot(), new Slot(), new Slot(), new Slot()};

    private final Slot[] sessionActions = {new Slot(), new Slot()};
    private final Slot primary = new Slot();
    private final Slot prevPage = new Slot();
    private final Slot nextPage = new Slot();
    private final Button[] tabButtons = new Button[Tab.values().length];
    private final Label[] info = new Label[INFO_LINES];
    private final Label[] syncLines = new Label[SYNC_POOL];

    private Label titleLine;
    private Label headerLine;
    private Label bannerHead;
    private Label bannerDetail;
    private Label pageLine;
    private Label statusLine;
    private EditBox input;

    private Tab tab = Tab.FRIENDS;

    /**
     * The selected row, held by name rather than by index on purpose: the roster
     * re-sorts whenever somebody comes online, and an index would then quietly
     * point at a different person than the one that was highlighted.
     */
    private String selected = "";

    private List<Row> rows = List.of();

    /** The two sub-views a friend's profile can open, both on the FRIENDS tab
     * and both mutually exclusive with the row list. Chat is deliberately not
     * one of them - conversation lives in the launcher's Chat tab only.
     *
     * <p>They are sub-views rather than tabs on purpose: the tab row is already
     * three labels wide at a 320px GUI, and neither of these means anything
     * without a friend selected - which is exactly what a sub-view expresses and
     * a tab doesn't.
     */
    private boolean playOpen;
    private boolean syncOpen;

    /** How many row buttons this window has room for. Set by {@link #layout}. */
    private int visibleRows = 1;
    /** How many Sync prose lines fit under the banner. Set by layout(). */
    private int syncRows = 1;
    /** The y below which the list region ends (above the pager). Set by layout(). */
    private int listBottom;
    private int page;

    /**
     * What the player has typed. Kept outside the widget because a window
     * resize rebuilds every widget, and losing a half-typed name to a resize is
     * exactly the kind of small bug that makes a UI feel broken.
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
    // tick. Snapshot compares by value, which is what makes this reliable.
    private long seenRevision = -1;
    private long seenSyncRevision = -1;
    private Tab seenTab;
    private String seenSelected = " ";
    private boolean seenBusy;
    private boolean bannerShown;

    // Resolved by layout(); read when rows are laid out and paged.
    private int panelX;
    private int panelW;
    private int listTop;

    public CubeonClientScreen(Screen parent) {
        this(parent, true);
    }

    /**
     * @param canInvite false opens the screen in "menu context": the Invite
     *                  action is blocked with an explanation, everything else
     *                  (joining and requests) works as normal.
     */
    public CubeonClientScreen(Screen parent, boolean canInvite) {
        super(Component.literal("Cubeon Client"));
        this.parent = parent;
        this.canInvite = canInvite;
        bridge.start();          // idempotent; the client initializer normally did it
        bridge.addViewer();      // paired with removed(); the constructor runs once
    }

    /** Size of the small Friends corner icon, and its inset from the screen edge. */
    public static final int ICON_W = 20;
    public static final int ICON_H = 20;
    public static final int ICON_INSET = 4;

    /**
     * The small Friends corner icon both the pause-menu and title-screen mixins
     * drop into Minecraft's own menus, docked top-left instead of joining the
     * menu's button column. Owned statically here so the two mixins share one
     * label (the pending badge), one size and one open action.
     *
     * <p>The icon is a quiet square when nothing is waiting; when there are
     * unanswered invites or incoming friend requests it shows their count, like
     * an app-icon badge, so news survives without a full-width button. The
     * screen it opens always explains what the badge was about.
     *
     * @param parent    the menu screen to come back to when this screen closes
     * @param canInvite whether an invite can ever complete from where the button
     *                  was tapped (yes in a singleplayer world, no on the title
     *                  screen or a remote server)
     */
    public static Button menuButton(Screen parent, boolean canInvite) {
        return Button
                .builder(iconLabel(), button -> Minecraft.getInstance().setScreen(
                        new CubeonClientScreen(parent, canInvite)))
                .bounds(0, 0, ICON_W, ICON_H)
                .tooltip(Tooltip.create(Component.literal(
                        "Cubeon Client - invites and friend requests")))
                .build();
    }

    /**
     * The label on the corner icon. Reads the cached snapshot, which never
     * blocks. The count (unanswered invites plus incoming friend requests) is
     * computed here because it is the same on every Minecraft era; how it is
     * drawn is the one thing that differs, so that part is handed to
     * {@link CornerIcon}, which is supplied per bracket (a real two-person
     * glyph on 26.x, plain text here until that bracket is split). Online
     * friends are not actionable, so they never move the count.
     */
    private static Component iconLabel() {
        Bridge.Snapshot snap = Bridge.get().snapshot();
        int invites = 0;
        for (Bridge.Friend friend : snap.friends()) {
            if (friend.invited()) {
                invites++;
            }
        }
        int pending = invites + snap.requestsIn().size();
        return CornerIcon.label(pending);
    }

    // ---- setup -----------------------------------------------------------

    @Override
    protected void init() {
        Snapshot snap = bridge.snapshot();
        // With no name there is no roster and no requests, so don't open on a
        // tab that can only be empty - open on the one that fixes it.
        if (!snap.claimed()) tab = Tab.FRIENDS;

        // Notices arriving while this screen is up are shown in its own status
        // line instead of the hotbar overlay, which needs a live player and is
        // invisible from a menu. init() runs on resize too; re-setting the same
        // sink is harmless.
        bridge.setScreenToastSink(screenNoticeSink);

        titleLine = line(this.title);
        headerLine = line(Component.empty());

        for (Tab value : Tab.values()) {
            Tab target = value;
            tabButtons[value.ordinal()] = add(Button
                    .builder(Component.empty(), b -> selectTab(target))
                    .bounds(0, 0, 40, BTN_H)
                    .build());
        }

        bannerHead = line(Component.empty());
        bannerDetail = line(Component.empty());
        for (Slot slot : sessionActions) {
            slot.button = add(slotButton(slot));
        }

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

        // The Sync prose pool. Created with the rows but never shown at the
        // same time as them: a report replaces the friend picker, it doesn't
        // join it.
        for (int i = 0; i < syncLines.length; i++) {
            syncLines[i] = line(Component.empty());
        }

        prevPage.button = add(slotButton(prevPage));
        nextPage.button = add(slotButton(nextPage));
        pageLine = line(Component.empty());

        for (Slot slot : actions) {
            slot.button = add(slotButton(slot));
        }

        input = new EditBox(this.font, 0, 0, 40, BTN_H, Component.literal("Name"));
        input.setMaxLength(16);
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
        apply(snap);
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
     * again whenever the session banner appears or disappears - the only thing
     * that moves the list.
     */
    private void layout() {
        panelW = Math.min(PANEL_MAX_W, this.width - 2 * GAP);
        panelX = (this.width - panelW) / 2;

        place(titleLine, panelX, TITLE_Y, panelW, true);
        place(headerLine, panelX, HEADER_Y, panelW);

        int tabW = (panelW - (tabButtons.length - 1) * GAP) / tabButtons.length;
        for (int i = 0; i < tabButtons.length; i++) {
            Button button = tabButtons[i];
            button.setWidth(tabW);
            button.setX(panelX + i * (tabW + GAP));
            button.setY(TAB_Y);
        }

        // Slot 0 (Cancel/Leave/Dismiss) is always present, so it takes the far
        // right and Retry sits to its left. The other way round would leave a
        // hole whenever Retry is hidden.
        int right = panelX + panelW;
        for (int i = 0; i < sessionActions.length; i++) {
            Button button = sessionActions[i].button;
            button.setWidth(SESSION_BTN_W);
            button.setX(right - (i + 1) * SESSION_BTN_W - i * GAP);
            button.setY(BANNER_Y + (BANNER_H - BTN_H) / 2);
        }
        int bannerTextW = panelW - 2 - sessionActions.length * (SESSION_BTN_W + GAP);
        place(bannerHead, panelX, BANNER_Y + 4, bannerTextW);
        place(bannerDetail, panelX, BANNER_Y + 18, bannerTextW);

        listTop = bannerShown ? BANNER_Y + BANNER_H + GAP : BANNER_Y;

        // Bottom-up: the chrome is fixed, and whatever vertical space is left
        // over becomes rows. One row always survives, however short the window.
        int pagerY = this.height - 102;
        int actionsY = this.height - 78;
        int footerY = this.height - 54;
        int statusY = this.height - 34;

        int room = pagerY - GAP - listTop;
        visibleRows = Math.max(1, Math.min(ROW_SLOTS, room / ROW_STEP));
        syncRows = Math.max(1, Math.min(SYNC_POOL, room / SYNC_LINE_STEP));
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

        int actionW = (panelW - (actions.length - 1) * GAP) / actions.length;
        for (int i = 0; i < actions.length; i++) {
            Button button = actions[i].button;
            button.setWidth(actionW);
            button.setX(panelX + i * (actionW + GAP));
            button.setY(actionsY);
        }

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
        long syncRevision = bridge.syncRevision();
        if (revision != seenRevision || syncRevision != seenSyncRevision
                || tab != seenTab || !selected.equals(seenSelected)
                || busy != seenBusy) {
            seenRevision = revision;
            seenSyncRevision = syncRevision;
            seenTab = tab;
            seenSelected = selected;
            seenBusy = busy;
            apply(bridge.snapshot());
        }
    }

    /** Rebuilds the rows and every mutable label from one snapshot. */
    private void apply(Snapshot snap) {
        // Sub-views belong to a friend's profile, so they cannot outlive the
        // FRIENDS tab or a selection.
        if (tab != Tab.FRIENDS || selected.isEmpty()) {
            playOpen = false;
            if (syncOpen) {
                syncOpen = false;
                bridge.setSyncFriend("");
            }
        }
        rows = buildRows(snap);

        // Drop a selection that no longer exists - a friend who removed you, or
        // a request that has just been answered. While a sub-view is up the
        // selection is the person it is about, so it is kept for when the Close
        // button brings the list back.
        if (!subViewOpen()) {

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

        for (Tab value : Tab.values()) {
            Button button = tabButtons[value.ordinal()];
            button.setMessage(Component.literal(tabLabel(value, snap)));
            // The current tab reads as pressed by being unclickable, the way
            // vanilla's own tabbed screens do it.
            button.active = value != tab && snap.claimed();
        }

        applySessionSlots(snap.session());
        if (snap.session().active() != bannerShown) {
            bannerShown = snap.session().active();
            layout();
        }

        applyRows();
        applyInfo(snap);
        applySync();
        applyActionSlots(snap);
        applyFooter(snap);
    }

    /** True while a friend's Play or Sync sub-view has replaced the row list. */
    private boolean subViewOpen() {
        return playOpen || syncOpen;
    }

    private String tabLabel(Tab value, Snapshot snap) {
        return switch (value) {
            case FRIENDS -> snap.friends().isEmpty()
                    ? "Friends"
                    : "Friends " + snap.onlineCount() + "/" + snap.friends().size();
            case REQUESTS -> snap.requestsIn().isEmpty()
                    ? "Requests"
                    : "Requests (" + snap.requestsIn().size() + ")";
            // Friends and requests are the only in-game sections.
        };
    }

    private List<Row> buildRows(Snapshot snap) {
        List<Row> out = new ArrayList<>();
        switch (tab) {
            case FRIENDS -> {
                if (subViewOpen()) {
                    break;   // a sub-view replaces the list, it doesn't join it
                }
                for (Friend friend : snap.friends()) {

                    ChatFormatting color = friend.invited() ? ChatFormatting.GOLD
                            : friend.online() ? ChatFormatting.WHITE : ChatFormatting.GRAY;
                    out.add(new Row(friend.name(), friend.label(), friend.presence(), color));
                }
            }
            case REQUESTS -> {
                for (String name : snap.requestsIn()) {
                    out.add(new Row(name, snap.peer(name).label(), "wants to be your friend", ChatFormatting.GOLD));
                }
                for (String name : snap.requestsOut()) {
                    out.add(new Row(name, snap.peer(name).label(), "request sent", ChatFormatting.GRAY));
                }
            }
        }
        return out;
    }

    /**
     * Points the row buttons at the current page. A slot past the end of the
     * list, or past what the window has room for, is hidden rather than left
     * showing a stale name.
     */
    private void applyRows() {
        boolean listTab = true;
        int first = page * visibleRows;
        for (int i = 0; i < rowSlots.length; i++) {
            Slot slot = rowSlots[i];
            int index = first + i;
            boolean used = listTab && i < visibleRows && index < rows.size();
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
                    isSelected ? "Click again to " + primaryRowVerb().toLowerCase(java.util.Locale.ROOT)
                            + " " + row.label() : "Select " + row.label())));
            String name = row.name();
            slot.action = () -> onRowClicked(name);
        }

        int pages = pageCount();
        boolean paged = listTab && pages > 1;
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
     * runs its obvious action. That is the mouse-wheel-free stand-in for the
     * double click a drawn list would have had.
     */
    private void onRowClicked(String name) {
        if (!name.equals(selected)) {
            selected = name;
            apply(bridge.snapshot());   // the action bar must reflect the new row now
            return;
        }
        // On the friends tab a second click means "play with them" - the one
        // thing the row is for. It opens the Play view rather than firing an
        // invite, because whether the right move is Invite or Join depends on
        // what the friend has already done, and the view says which.
        if (tab == Tab.FRIENDS) {
            openPlay(name);
            return;
        }
        Slot preferred = actions[0];
        if (preferred.button.visible && preferred.button.active && preferred.action != null) {
            preferred.action.run();
        }
    }

    private String primaryRowVerb() {
        if (tab == Tab.REQUESTS) {
            return "Accept";
        }
        return "play with";
    }

    private void openPlay(String name) {
        selected = name;
        playOpen = true;
        syncOpen = false;
        page = 0;
        setStatus("", false);
        apply(bridge.snapshot());
    }

    private void closePlay() {
        playOpen = false;
        setStatus("", false);
        apply(bridge.snapshot());
    }

    /**
     * Opens the Sync view. Only starts the poll stream - the compare itself
     * costs relay traffic, so it waits for the player to press Compare.
     */
    private void openSync(String name) {
        selected = name;
        syncOpen = true;
        playOpen = false;
        page = 0;
        setStatus("", false);
        bridge.setSyncFriend(name);
        apply(bridge.snapshot());
    }

    /**
     * Closes the Sync view and drops the relay room with it.
     *
     * <p>The close POST is fired and forgotten rather than run through
     * {@link #submit}: leaving the view must be instant, and a room the launcher
     * failed to close is reaped by its own idle janitor anyway.
     */
    private void closeSync() {
        String handle = selected;
        boolean started = !bridge.syncReport().idle();
        syncOpen = false;
        if (!selected.isEmpty()) {
            bridge.clearSyncFriend(selected);
        }
        setStatus("", false);
        apply(bridge.snapshot());
        if (started && !handle.isEmpty()) {
            Thread closer = new Thread(() -> bridge.closeSync(handle),
                    "cubeon-client-syncclose");
            closer.setDaemon(true);
            closer.start();
        }
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

    /* The prose block: every empty list, and nowhere at all
     * while the sync report is up (the sync labels own that region). */
    private void applyInfo(Snapshot snap) {
        List<Component> lines = new ArrayList<>();
        if (playOpen) {
            lines.add(colored("Play with " + peerLabel(selected), ChatFormatting.WHITE));
            for (String line : wrap(playBody(snap), panelW - 8)) {
                lines.add(colored(line, ChatFormatting.GRAY));
            }
        } else if (syncOpen) {
            // The sync report owns the whole list region; nothing else belongs
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

    /** The Play sub-view's prose: what each of its two buttons will do. */
    private String playBody(Snapshot snap) {
        Friend friend = find(snap, selected);
        if (friend == null) {
            return peerLabel(selected) + " is no longer on your friends list.";
        }
        if (friend.invited()) {
            return peerLabel(selected) + " has a world open for you. Press Join and Cubeon "
                    + "connects you - it syncs any mods you're missing on the way in.";
        }
        if (!friend.online()) {
            return peerLabel(selected) + " is offline right now. Both of you have to be in "
                    + "Minecraft with Cubeon running to play together.";
        }
        if (!canInvite) {
            return "Invite needs a world of your own - it ends in \"open to LAN\", "
                    + "which the title screen and other people's servers can't do. "
                    + "Ask to join works from anywhere.";
        }
        return "Invite opens your own world to " + peerLabel(selected) + " (you then open it to "
                + "LAN from this menu). Ask to join asks them to host instead.";
    }

    private String emptyHead(Snapshot snap) {
        if (!snap.launcherUp()) {
            return "Cubeon launcher not running";
        }
        if (!snap.claimed()) {
            return "No Cubeon name yet";
        }
        return switch (tab) {
            case REQUESTS -> "No pending requests";
            default -> "No friends yet";
        };
    }

    private String emptyBody(Snapshot snap) {
        if (!snap.launcherUp()) {
            return snap.problem().isEmpty()
                    ? "Start Cubeon and this screen fills in by itself." : snap.problem();
        }
        if (!snap.claimed()) {
            return "Open the Cubeon launcher once to finish setting up.";
        }
        if (tab == Tab.REQUESTS) {
            return "Friend requests from other players show up here.";
        }
        // Add-by-ID: the UID is the address. Names are display only, so the
        // ID is both what you type and what you hand out.
        String idLine = snap.youUid().isEmpty()
                ? "Your ID appears once the launcher connects."
                : "Your friends can add you with your Cubeon ID: "
                  + snap.youUid() + ".";
        return "Type a friend's 8-digit Cubeon ID below and press Add. "
                + idLine;
    }

    /**
     * The Sync report, drawn into the sync label pool.
     *
     * <p>The sentences come pre-rendered from the launcher; see
     * {@link Bridge.SyncReport}. Colour is decided here, because only this side
     * knows what a red line looks like.
     */
    private void applySync() {
        if (!syncOpen) {
            return;
        }
        Bridge.SyncReport report = bridge.syncReport();
        List<Component> lines = new ArrayList<>();
        lines.add(colored("Sync with " + peerLabel(selected), ChatFormatting.WHITE));
        if (report.idle()) {
            for (String line : wrap("Press Compare to see whether your Minecraft "
                    + "matches theirs. Nothing is sent until you do, and what is "
                    + "sent is encrypted end to end.", panelW - 8)) {
                lines.add(colored(line, ChatFormatting.GRAY));
            }
        }
        for (String line : report.lines()) {
            ChatFormatting color = ChatFormatting.GRAY;
            if (report.failed()) {
                color = ChatFormatting.RED;
            } else if (line.startsWith("Nothing missing")) {
                color = ChatFormatting.GREEN;
            } else if (line.startsWith("Minecraft version differs")
                    || line.startsWith("Mod loader differs")
                    || line.startsWith("You're missing")) {
                color = ChatFormatting.GOLD;
            } else if (line.startsWith("Done.")) {
                color = ChatFormatting.GREEN;
            }
            for (String wrapped : wrap(line, panelW - 8)) {
                lines.add(colored(wrapped, color));
            }
        }
        if (report.working()) {
            lines.add(colored(ellipsis(), ChatFormatting.YELLOW));
        }
        int shown = Math.min(lines.size(), Math.min(syncRows, syncLines.length));
        for (int i = 0; i < shown; i++) {
            Label label = syncLines[i];
            // Top-anchored: a report is read from the first line down.
            place(label, panelX + 4, listTop + 4 + i * SYNC_LINE_STEP, panelW - 8);
            show(label, true);
            say(label, lines.get(i));
        }
    }

    private void applyActionSlots(Snapshot snap) {

        for (Slot slot : actions) {
            slot.action = null;
            slot.button.visible = (tab == Tab.FRIENDS || tab == Tab.REQUESTS)
                    && !snap.session().needsGateChoice();
            slot.button.active = false;
            slot.button.setTooltip(null);
        }

        if (snap.session().needsGateChoice()) {
            // The worldgate decision owns the footer; the action bar would
            // just offer actions against a world that isn't open yet.
            return;
        }

        if (tab == Tab.REQUESTS) {
            label(actions[0], "Accept");
            label(actions[1], "Decline");
            actions[2].button.visible = false;
            actions[3].button.visible = false;
            if (selected.isEmpty()) {
                return;
            }
            String handle = selected;
            String who = peerLabel(handle);
            if (snap.requestsIn().contains(handle)) {
                bind(actions[0], "Accepting " + who + "...", who + " is now your friend.",
                        () -> bridge.acceptRequest(handle));
                bind(actions[1], "Declining...", "Declined " + who + "'s request.",
                        () -> bridge.declineRequest(handle));
            } else {
                blocked(actions[0], who + " hasn't answered your request yet.");
                blocked(actions[1], who + " hasn't answered your request yet.");
            }
            return;
        }

        if (playOpen) {
            applyPlaySlots(snap);
            return;
        }
        if (syncOpen) {
            applySyncSlots();
            return;
        }

        // A mutual friend's profile. "add all these if missing": Play and Sync
        // are the things you do with a friend; Whitelist and Remove are the
        // administration that was already here.
        label(actions[0], "Play");
        label(actions[1], "Sync");
        label(actions[2], "Whitelist");
        label(actions[3], "Remove");
        if (selected.isEmpty()) {
            // Left visible but dead, so the bar doesn't jump as you click around.
            return;
        }

        String handle = selected;
        String who = peerLabel(handle);
        Friend friend = find(snap, handle);
        boolean whitelisted = friend != null && friend.whitelisted();

        // Play and Sync open something local - no launcher round trip - so they
        // set their action directly instead of going through bind().
        actions[0].action = () -> openPlay(handle);
        actions[0].button.active = !busy;
        tip(actions[0], "Invite " + who + " to your world, or ask to join theirs.");

        if (friend == null || !friend.online()) {
            blocked(actions[1], who + " is offline. Sync is available when they come online.");
        } else {
            actions[1].action = () -> openSync(handle);
            actions[1].button.active = !busy;
            tip(actions[1], "Check whether your Minecraft matches " + who + "'s, and "
                    + "pull any mods you're missing.");
        }

        label(actions[2], whitelisted ? "- Whitelist" : "+ Whitelist");
        bind(actions[2],
                whitelisted ? "Removing " + who + " from the whitelist..."
                            : "Whitelisting " + who + "...",
                whitelisted ? who + " can no longer join your Cubeon server."
                            : who + " can now join your Cubeon server.",
                () -> bridge.setWhitelisted(handle, !whitelisted));
        tip(actions[2], "Whether " + who + " may join the Cubeon server this launcher "
                + "hosts. Separate from world invites.");

        bind(actions[3], "Removing " + who + "...", "Removed " + who + ".",
                () -> bridge.removeFriend(handle));
        tip(actions[3], "Take " + who + " off your friends list.");
    }

    /**
     * The Play sub-view's bar. Both halves of "send req to join or invite": one
     * button hosts for them, the other asks them to host for us. They could
     * never share a single slot, which is why Play opens a view rather than
     * firing an action.
     */
    private void applyPlaySlots(Snapshot snap) {
        String handle = selected;
        String who = peerLabel(handle);
        Friend friend = find(snap, handle);
        boolean online = friend != null && friend.online();
        boolean invited = friend != null && friend.invited();

        label(actions[0], invited ? "Join" : "Invite");
        label(actions[1], "Ask to join");
        label(actions[2], "Close");
        actions[3].button.visible = false;

        if (invited) {
            bind(actions[0], "Joining " + who + "'s world...", "",
                    () -> bridge.join(handle));
            tip(actions[0], "Join the world " + who + " already opened for you.");
        } else if (!canInvite) {
            blocked(actions[0], "Invites work only from a world you host - "
                    + "start or load one, then invite.");
        } else if (online) {
            bind(actions[0], "Inviting " + who + "...", "", () -> bridge.invite(handle));
            tip(actions[0], "Open your world to " + who + ". Cubeon connects you as "
                    + "soon as you open it to LAN from this menu.");
        } else {
            blocked(actions[0], who + " has to be online to be invited.");
        }

        if (online) {
            bind(actions[1], "Asking " + who + "...",
                    "Asked " + who + " to open their world to you.",
                    () -> bridge.askToJoin(handle));
            tip(actions[1], "Sends " + who + " a request to host. They answer by "
                    + "pressing Invite on their side.");
        } else {
            blocked(actions[1], who + " is offline right now.");
        }

        actions[2].action = this::closePlay;
        actions[2].button.active = !busy;
        tip(actions[2], "Back to your friends list.");
    }

    /** The Sync sub-view's bar: Compare, Download mods, Close. */
    private void applySyncSlots() {
        String handle = selected;
        String who = peerLabel(handle);
        Bridge.SyncReport report = bridge.syncReport();
        label(actions[0], report.idle() ? "Compare" : "Refresh");
        label(actions[1], "Fix");
        label(actions[2], "Close");
        actions[3].button.visible = false;

        if (report.working()) {
            blocked(actions[0], "Working on it...");
        } else {
            bind(actions[0], "Comparing with " + who + "...", "",
                    () -> bridge.startSync(handle));
            tip(actions[0], "Ask " + who + " what Minecraft and mods they're running. "
                    + "The answer is encrypted end to end.");
        }

        if (report.canDownload()) {
            bind(actions[1], "Downloading " + report.missing() + " mod(s)...", "",
                    () -> bridge.downloadMods(handle));
            tip(actions[1], "Pulls the " + report.missing() + " mod(s) you're missing "
                    + "into Cubeon's global mods folder and links them into this "
                    + "profile. Relaunch Minecraft afterwards.");
        } else if (report.idle()) {
            blocked(actions[1], "Compare first.");
        } else if (!report.versionOk()) {
            blocked(actions[1], "Different Minecraft version - switch the Play tab to "
                    + report.themVersion() + " and relaunch first.");
        } else if (!report.loaderOk()) {
            blocked(actions[1], "Different mod loader - switch to "
                    + report.themLoader() + " and relaunch first.");
        } else if (report.missing() == 0) {
            blocked(actions[1], "You already have everything they run.");
        } else {
            blocked(actions[1], report.failed() && !report.error().isEmpty()
                    ? report.error() : "Nothing to download right now.");
        }

        actions[2].action = this::closeSync;
        actions[2].button.active = !busy;
        tip(actions[2], "Back to your friends list.");
    }

    private void applySessionSlots(Session session) {
        for (Slot slot : sessionActions) {
            slot.action = null;
            slot.button.visible = false;
            slot.button.active = false;
            slot.button.setTooltip(null);
        }
        show(bannerHead, session.active());
        show(bannerDetail, session.active());
        if (!session.active()) {
            return;
        }

        int textW = panelW - 2 - sessionActions.length * (SESSION_BTN_W + GAP);
        String headline = session.headline() + (session.working() ? ellipsis() : "");
        say(bannerHead, colored(trim(headline, textW), switch (session.state()) {
            case "failed" -> ChatFormatting.RED;
            case "connected" -> ChatFormatting.GREEN;
            case "ended" -> ChatFormatting.GRAY;
            default -> ChatFormatting.GOLD;
        }));
        say(bannerDetail, colored(trim(session.detail(), textW), ChatFormatting.GRAY));

        if (session.endable()) {
            label(sessionActions[0], session.host() ? "Cancel" : "Leave");
            bind(sessionActions[0], "Ending the session...", "", bridge::cancelSession);
        } else {
            // Nothing left to end, but the banner still needs a way to go away.
            label(sessionActions[0], "Dismiss");
            bind(sessionActions[0], "Clearing...", "", bridge::cancelSession);
        }
        if (session.canRetry()) {
            label(sessionActions[1], "Retry");
            bind(sessionActions[1], "Trying again...", "", bridge::retrySession);
        }
    }

    private void applyFooter(Snapshot snap) {
        primary.action = null;
        primary.button.setTooltip(null);
        primary.button.active = false;

        boolean typing = false;
        Session session = snap.session();
        if (session.needsGateChoice()) {
            // The worldgate decision outranks whatever tab is open: the
            // banner explains why, this footer is how. Empty box + Save is
            // the host's Skip (an ungated world); the joiner's button is
            // Join, which refuses an empty box (an empty password is never
            // a valid answer to a gated world).
            typing = true;
            input.setMaxLength(32);
            if (session.host()) {
                input.setHint(Component.literal("World password (empty = skip)"));
                label(primary, "Save");
                primary.action = this::submitWorldGate;
                primary.button.active = !busy;
            } else {
                input.setHint(Component.literal("World password"));
                label(primary, "Join");
                primary.action = this::submitJoinPassword;
                primary.button.active = !busy;
            }
        } else {
            switch (tab) {
            case FRIENDS -> {
                if (subViewOpen()) {
                    // A sub-view is about one friend you already have; adding
                    // another from inside it would be a non-sequitur, and the
                    // action bar is that view's whole footer.
                    break;
                }
                typing = true;
                input.setMaxLength(16);
                // The Cubeon ID is the address (8 digits); a friend's name
                // still works, but IDs are the thing you copy and share.
                input.setHint(Component.literal("Add by Cubeon ID or name"));
                label(primary, "Add");
                primary.action = this::submitAdd;
                primary.button.active = !busy && snap.claimed();
            }
            case REQUESTS -> {
                // No text entry on this tab.
            }
            }
        }
        if (session.needsGateChoice()) {
            // In gate mode the primary IS the Save/Join button, on every tab.
            primary.button.visible = true;
        } else {
            // Requests and sub-views have no add field.
            primary.button.visible = tab == Tab.FRIENDS && !subViewOpen();
        }
        primary.button.active = primary.button.active && primary.button.visible;
        input.visible = typing;
        input.setEditable(typing && !busy);

        String footnote = status;
        ChatFormatting color = statusIsError ? ChatFormatting.RED : ChatFormatting.YELLOW;
        if (footnote.isEmpty() && tab == Tab.FRIENDS && !subViewOpen()
                && !session.needsGateChoice()) {
            footnote = hint(snap);
            color = ChatFormatting.GRAY;
        }
        show(statusLine, !footnote.isEmpty());
        say(statusLine, colored(trim(footnote, panelW), color));
    }

    /** The one line of guidance under the list on the friends tab. */
    private String hint(Snapshot snap) {
        if (selected.isEmpty()) {
            return snap.friends().isEmpty() ? ""
                    : "Pick a friend: play or sync with them.";
        }
        Friend friend = find(snap, selected);
        if (friend == null) {
            return "";
        }
        if (friend.invited()) {
            return peerLabel(selected) + " has a world open for you - press Play.";
        }
        if (friend.online()) {
            return "Play or check what " + peerLabel(selected) + " is running.";
        }
        return peerLabel(selected) + " is offline - Play and Sync are unavailable.";
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

    private void label(Slot slot, String text) {
        slot.button.setMessage(Component.literal(text));
    }

    private void bind(Slot slot, String working, String done, Supplier<Result> call) {
        slot.action = () -> submit(working, done, call);
        slot.button.active = !busy;
    }

    /** Explains what a live button does. Does not change whether it is enabled. */
    private void tip(Slot slot, String text) {
        slot.button.setTooltip(Tooltip.create(Component.literal(text)));
    }

    /** Greys a button out and says why, instead of letting it fail on click. */
    private void blocked(Slot slot, String reason) {
        slot.button.active = false;
        slot.button.setTooltip(Tooltip.create(Component.literal(reason)));
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

    /** A text-only busy marker - no texture, so it draws on every version. */
    private String ellipsis() {
        return " " + ".".repeat((int) ((System.currentTimeMillis() / 350) % 4));
    }

    // ---- actions ---------------------------------------------------------

    /**
     * Runs a launcher call on a worker thread and reports back on the main one.
     *
     * <p>Every {@link Bridge} action is a blocking HTTP request, and
     * {@code /rename} can take seconds because the launcher re-claims the name
     * against Cubeon's server. Calling one inline would freeze the game.
     */
    private void submit(String working, String done, Supplier<Result> call) {
        submit(working, done, call, false);
    }

    /**
     * @param stickyDone keep the success line up until the player does something
     *                   else, instead of letting the next launcher notice
     *                   overwrite it. Used by rename, whose confirmation is the
     *                   only feedback that the new name actually took.
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

    private void submitAdd() {
        String name = input.getValue().trim();
        boolean cubeonId = name.matches("\\d{8}");
        String problem = cubeonId ? null : Bridge.checkName(name);
        if (problem != null) {
            flash(problem);
            return;
        }
        Snapshot snap = bridge.snapshot();
        // Can't add yourself - by the relay's internal name, or (the realistic
        // case under the UID system) by your own Cubeon ID.
        if (name.equalsIgnoreCase(snap.you())
                || (!snap.youUid().isEmpty() && name.equals(snap.youUid()))) {
            flash("You can't add yourself.");
            return;
        }
        for (Friend friend : snap.friends()) {
            if (friend.name().equalsIgnoreCase(name)) {
                flash(friend.name() + " is already your friend.");
                return;
            }
        }
        submit("Looking up Cubeon ID " + name + "...",
                "Friend request sent to " + name + ".",
                () -> clearInputOnSuccess(bridge.addFriend(name)));
    }

    /**
     * Host: the worldgate decision. An empty box means Skip - the world opens
     * to anyone the invite reaches - and anything else is the password. The
     * launcher validates the length and words the error; the invite only
     * rings out once this lands, whichever way it goes.
     */
    private void submitWorldGate() {
        String password = input.getValue();
        password = password == null ? "" : password.strip();
        String saved = password;
        submit("Saving the world password...",
                password.isEmpty()
                        ? "No password - anyone your invite reaches can join."
                        : "World password saved - inviting your friend...",
                () -> clearInputOnSuccess(bridge.setWorldGate(saved)));
    }

    /**
     * Joiner: answer the host's password challenge. The launcher turns the
     * password into a proof and sends it; a wrong answer comes back as a
     * notice from the host (with the tries that are left), and the box
     * re-appears for the next round.
     */
    private void submitJoinPassword() {
        String password = input.getValue();
        password = password == null ? "" : password.trim();
        if (password.isEmpty()) {
            flash("Type the world's password.");
            return;
        }
        String answer = password;
        submit("Checking the password...", "",
                () -> clearInputOnSuccess(bridge.sendJoinPassword(answer)));
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
     * named X." or a request arriving on its own is visible from a menu - the
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
            // A sticky line (a rename confirmation) outranks routine news: the
            // launcher emits its own notice for the very action we just
            // confirmed, and overwriting ours would hide the confirmation. A
            // real error still gets through - it's the more useful of the two.
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

    private void selectTab(Tab target) {
        if (tab == target) {
            return;
        }
        // A compare view belongs to one friend on the FRIENDS tab. The room
        // itself is left to time out rather than closed here, so stepping onto
        // another tab and back doesn't throw away a finished compare.
        if (syncOpen) {
            bridge.setSyncFriend("");
        }
        syncOpen = false;
        playOpen = false;
        tab = target;
        selected = "";
        page = 0;
        setStatus("", false);
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
        // Leaving the screen stops the sync poll stream following you into the
        // world - polling /sync with the screen shut would keep asking the
        // launcher for a report nobody is reading.
        if (!selected.isEmpty()) {
            bridge.clearSyncFriend(selected);
        }
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
