package com.cubeon.client;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import java.util.function.Consumer;

/**
 * Everything this mod knows about the launcher, and the only thing that talks
 * to it.
 *
 * <p>The launcher owns the friends account, the roster and the whole P2P
 * session state machine (see cubeon/friends_service.py); it publishes them over
 * a token-authenticated HTTP API bound to 127.0.0.1 (cubeon/local_api.py). This
 * class polls that API on ONE daemon thread and publishes an immutable
 * {@link Snapshot}, which the screen reads without ever blocking.
 *
 * <p>That split is the fix for the mod's worst bug rather than a style choice.
 * The screen used to call {@code isLauncherUp()}, {@code friends()},
 * {@code requestsIn()} and {@code currentName()} straight from
 * {@code Screen.init()} - four blocking HTTP round trips, each up to 1.5s, on
 * the render thread. Opening the pause menu could therefore freeze Minecraft
 * for several seconds, and resizing the window did it all over again.
 *
 * <p>Deliberately contains NO Minecraft imports: it is plain Java, so it
 * compiles and unit-tests against a bare JDK (mod/tools/SelfTest.java) and
 * carries no dependency on any particular Minecraft version.
 */
public final class Bridge {

    /** Polling period while a Friends screen is open. */
    private static final long ACTIVE_POLL_MS = 1_200;
    /** Polling period with no screen open - just enough to catch notifications. */
    private static final long IDLE_POLL_MS = 6_000;
    /** Backoff steps used while the launcher looks absent. */
    private static final long[] DOWN_BACKOFF_MS = {1_000, 2_000, 4_000, 8_000};

    private static final Duration CONNECT_TIMEOUT = Duration.ofMillis(900);
    private static final Duration READ_TIMEOUT = Duration.ofMillis(2_000);
    /**
     * POST /rename re-claims the name against Cubeon's server, so it is slow.
     *
     * <p>30s, not 15: /rename is the one action that still blocks on a REST
     * round trip inside the launcher (friends.claim(), itself on a 15s budget),
     * so a 15s limit here could time out an action that was about to succeed and
     * report "Couldn't reach the Cubeon launcher" for a rename that actually
     * landed. Every other POST answers in microseconds.
     */
    private static final Duration ACTION_TIMEOUT = Duration.ofSeconds(30);


    private static final Path TOKEN_FILE = Path.of(
            System.getProperty("user.home", "."), ".cubeon_launcher", "local_api.json");

    private static Bridge instance;

    // ---- value types -----------------------------------------------------

    /** One roster entry, exactly as the launcher's Friends list showed it. */
    public record Friend(String name, boolean online, String version, String status,
                         boolean invited, boolean whitelisted) {

        /** The grey sub-line under the name. Ported from friends_tab's presence_line(). */
        public String presence() {
            if (version != null && !version.isBlank()) {
                return "Playing " + version;
            }
            if (!online) {
                return "Offline";
            }
            if (status == null || status.isBlank()) {
                return "Online";
            }
            return Character.toUpperCase(status.charAt(0)) + status.substring(1);
        }
    }

    /** The live P2P world session, or {@link #NONE} when there isn't one. */
    public record Session(String state, String peer, String error, boolean host,
                          String quality, boolean canRetry) {

        public static final Session NONE = new Session("", "", "", false, "", false);

        public boolean active() {
            return state != null && !state.isEmpty();
        }

        /** True while Cubeon is still working - the screen shows a busy marker. */
        public boolean working() {
            return switch (state) {
                case "hosting_wait_port", "ringing_out", "connecting", "launching",
                     "verifying" -> true;
                default -> false;
            };
        }

        /** True while the screen owes the session a password decision. */
        public boolean needsGateChoice() {
            return "gate_wait".equals(state) || "password_needed".equals(state);
        }

        /** True when there is something for a Cancel/Leave button to end. */
        public boolean endable() {
            return active() && !"failed".equals(state) && !"ended".equals(state);
        }

        /** One human sentence about this session. Ported from render_p2p_banner(). */
        public String headline() {
            String who = peer == null || peer.isEmpty() ? "your friend" : peer;
            return switch (state) {
                case "hosting_wait_port" -> "Open your world to LAN from this menu.";
                case "gate_wait" -> "Set a password for your world.";
                case "verifying" -> "Checking the world password...";
                case "password_needed" -> who + "'s world needs a password.";
                case "ringing_out" -> "Inviting " + who + " to your world...";
                case "ringing_in" -> who + " invited you to their world.";
                case "connecting" -> "Connecting to " + who + "...";
                case "connected" -> "Connected to " + who + "'s world.";
                case "launching" -> "Launching Minecraft into " + who + "'s world...";
                case "ended" -> "The world session with " + who + " ended.";
                case "failed" -> error == null || error.isEmpty()
                        ? "Couldn't connect to " + who + "." : error;
                default -> active() ? state : "No world session right now.";
            };
        }

        /** A second, dimmer line of detail, or "" when there's nothing to add. */
        public String detail() {
            return switch (state) {
                case "hosting_wait_port" ->
                        "Cubeon invites your friend the moment it sees the LAN port.";
                case "gate_wait" ->
                        "Type one below and press Save, or save it empty to skip.";
                case "verifying" -> "Your friend is typing it now.";
                case "password_needed" -> "Type it below and press Join.";
                case "connecting" -> "Syncing mods and opening a direct path.";
                case "connected" -> quality == null ? "" : quality;
                case "launching" -> "The connection is ready - handing it to Minecraft.";
                default -> "";
            };
        }
    }

    /**
     * One consistent picture of the launcher. Immutable and compared by value,
     * so the screen can rebuild its widgets only when something really changed
     * rather than on every single poll.
     */
    public record Snapshot(boolean launcherUp, boolean connected, boolean available,
                           String you, List<Friend> friends, List<String> requestsIn,
                           List<String> requestsOut, Session session, String problem,
                           String modStamp) {

        public static final Snapshot DOWN = new Snapshot(
                false, false, true, "", List.of(), List.of(), List.of(), Session.NONE,
                "Looking for the Cubeon launcher...", "");

        /** True once a Cubeon name is owned by this machine. */
        public boolean claimed() {
            return you != null && !you.isEmpty();
        }

        public int onlineCount() {
            int n = 0;
            for (Friend f : friends) {
                if (f.online()) {
                    n++;
                }
            }
            return n;
        }

        /** The header line: who you are and whether presence is flowing. */
        public String connectionLine() {
            if (!launcherUp) {
                return "Cubeon launcher not found";
            }
            if (!available) {
                return "Realtime add-on missing in the launcher";
            }
            if (!claimed()) {
                return "No Cubeon name yet";
            }
            return connected ? "Connected as " + you : "Offline - reconnecting as " + you;
        }
    }

    /** The outcome of a POST. {@code error} is empty exactly when ok. */
    public record Result(boolean ok, String error) {
        public static final Result OK = new Result(true, "");

        public static Result fail(String message) {
            return new Result(false, message == null ? "" : message);
        }
    }

    /** A launcher-side notification, shown in chat and on the screen. */
    public record Toast(long seq, String text, boolean error) {}

    /**
     * One Cubeon player as the launcher's {@code /players} route reports them.
     *
     * <p>This is the launcher's own answer about its account holders - the
     * roster names plus whatever it knows about their skin, cape and stats.
     * {@code skin}/{@code cape} are display strings (a file name, or "" when
     * the launcher knows of none): the mod never fetches pixels itself, it
     * only relays what the launcher already has on disk.
     */
    public record CubeonPlayer(String name, boolean online, String skin, String cape,
                               String version, String status) {

        /** The grey sub-line under the name, same wording as Friend.presence(). */
        public String presence() {
            if (version != null && !version.isBlank()) {
                return "Playing " + version;
            }
            if (!online) {
                return "Offline";
            }
            if (status == null || status.isBlank()) {
                return "Online";
            }
            return Character.toUpperCase(status.charAt(0)) + status.substring(1);
        }
    }

    /** One line of a chat transcript, as the launcher serves it (decrypted). */
    public record ChatMessage(long seq, boolean incoming, String name, String text) {}

    /**
     * The launcher's decrypted transcript for one friend. {@code friend} is ""
     * when no conversation is open, which is what the screen reads to decide
     * between the friend picker and the transcript.
     */
    public record ChatConversation(String friend, List<ChatMessage> messages) {

        public static final ChatConversation NONE = new ChatConversation("", List.of());

        public boolean open() {
            return friend != null && !friend.isEmpty();
        }
    }

    /**
     * The launcher's profile-compare report for one friend - the Sync view.
     *
     * <p>{@code lines} is pre-rendered prose from the launcher, deliberately:
     * this screen is widget-only (no custom render pass), so text can only reach
     * the player through a fixed pool of label widgets, and the wording lives
     * better in one Python file than duplicated across two Minecraft-era source
     * trees. Everything else here exists so the buttons can be enabled or
     * disabled without parsing that prose.
     */
    public record SyncReport(String friend, String state, String error,
                             boolean encrypted, String youVersion, String youLoader,
                             int youMods, String themVersion, String themLoader,
                             int themMods, boolean versionOk, boolean loaderOk,
                             int missing, int extra, boolean canDownload,
                             int downloadDone, int downloadTotal,
                             boolean needsRelaunch, List<String> lines) {

        public static final SyncReport NONE = new SyncReport(
                "", "", "", false, "", "", 0, "", "", 0, true, true, 0, 0, false,
                0, 0, false, List.of());

        public boolean open() {
            return friend != null && !friend.isEmpty();
        }

        /** True while the launcher is mid-request - the buttons show busy. */
        public boolean working() {
            return "asking".equals(state) || "downloading".equals(state);
        }

        public boolean failed() {
            return "error".equals(state);
        }

        /** True before anything has been asked, so the view offers Compare. */
        public boolean idle() {
            return state == null || state.isEmpty() || "idle".equals(state);
        }
    }

    // ---- state -----------------------------------------------------------

    private final HttpClient http = HttpClient.newBuilder()
            .connectTimeout(CONNECT_TIMEOUT)
            .followRedirects(HttpClient.Redirect.NEVER)
            .build();

    private final Object wakeLock = new Object();
    private final AtomicInteger viewers = new AtomicInteger();
    private final AtomicLong revision = new AtomicLong();

    private volatile Snapshot current = Snapshot.DOWN;
    private volatile Consumer<Toast> toastSink;
    private volatile Thread poller;

    /**
     * The Friends screen while it is open. Notices are routed here instead of
     * the overlay sink, which needs a live player and is invisible from a menu -
     * exactly when this screen is up.
     */
    private volatile Consumer<Toast> screenToastSink;

    private boolean wakeRequested;

    // ---- chat state ------------------------------------------------------
    // A second, independent poll stream: while a chat partner is set, the poll
    // thread also asks the launcher for new lines since the last one it saw.
    // The transcript is capped to the most recent _CHAT_KEEP, mirroring the
    // launcher's own bounded ring, so a session left running for a week can't
    // grow this list without bound.
    private static final int CHAT_KEEP = 200;

    private final Object chatLock = new Object();
    private String chatFriend = "";          // "" = no chat open (guarded by chatLock)
    private long chatCursor = -1;            // guarded by chatLock; -1 = full page
    private ChatConversation chatCurrent = ChatConversation.NONE;  // guarded by chatLock
    private final AtomicLong chatRevision = new AtomicLong();

    // ---- sync state ------------------------------------------------------
    // A third poll stream, on the same terms as chat: it only costs anything
    // while the Sync view is actually open on a friend.
    private final Object syncLock = new Object();
    private String syncFriend = "";                        // guarded by syncLock
    private SyncReport syncCurrent = SyncReport.NONE;      // guarded by syncLock

    // ---- players state ----------------------------------------------------
    // A fourth poll stream, on the same terms as chat and sync: the launcher's
    // /players route. Unlike the other two it is not opened and closed by a
    // view - it is cheap (one localhost GET) and the Online panel, the Profile
    // view and the nametag badge all read it, so it rides along on every
    // roster poll. An older launcher has no route at all; the empty list that
    // degrades to is the correct answer for every reader.
    private final AtomicLong playersRevision = new AtomicLong();
    private volatile List<CubeonPlayer> players = List.of();
    private final AtomicLong syncRevision = new AtomicLong();

    // Touched by the poll thread only.
    private String baseUrl;
    private String token;
    private long tokenStamp = -1;
    private int downStreak;
    private long eventCursor = -1;   // -1 asks the launcher to skip the backlog
    private String ownStamp;         // lazily fingerprinted jar hash, "" unknown
    private boolean staleWarned;     // the "restart Minecraft" notice fired once

    private Bridge() {
    }

    public static synchronized Bridge get() {
        if (instance == null) {
            instance = new Bridge();
        }
        return instance;
    }

    // ---- lifecycle -------------------------------------------------------

    /** Starts the single poll thread. Safe to call more than once. */
    public synchronized void start() {
        if (poller != null) {
            return;
        }
        Thread t = new Thread(this::pollLoop, "cubeon-client-poll");
        t.setDaemon(true);
        poller = t;
        t.start();
    }

    /** Called by the screen while it is on-screen, so polling speeds up. */
    public void addViewer() {
        viewers.incrementAndGet();
        wake();
    }

    public void removeViewer() {
        viewers.updateAndGet(n -> n > 0 ? n - 1 : 0);
    }

    /** Ask for a refresh now instead of at the end of the current poll period. */
    public void wake() {
        synchronized (wakeLock) {
            wakeRequested = true;
            wakeLock.notifyAll();
        }
    }

    /** Never null, never blocks. */
    public Snapshot snapshot() {
        return current;
    }

    /** Bumped only when {@link #snapshot()} actually changed. */
    public long revision() {
        return revision.get();
    }

    /** The friend whose chat is open, "" when none. Never blocks. */
    public String chatFriend() {
        synchronized (chatLock) {
            return chatFriend;
        }
    }

    /** Never null, never blocks. friend()=="" when no chat is open. */
    public ChatConversation chat() {
        synchronized (chatLock) {
            return chatCurrent;
        }
    }

    /** Bumped only when {@link #chat()} actually changed. */
    public long chatRevision() {
        return chatRevision.get();
    }

    /**
     * Opens (or closes, with an empty name) the chat for one friend, resetting
     * the poll cursor so the next refresh pulls a full page of history rather
     * than only what arrived since a previous conversation.
     */
    public void setChatFriend(String friend) {
        String next = friend == null ? "" : friend;
        synchronized (chatLock) {
            if (!next.equals(chatFriend)) {
                chatFriend = next;
                chatCursor = -1;
                publishChatLocked(new ChatConversation(next, List.of()));
                wake();
            }
        }
    }

    /** Where launcher notifications are delivered. Called on the poll thread. */
    public void setToastSink(Consumer<Toast> sink) {
        this.toastSink = sink;
    }

    /** The friend whose Sync view is open, "" when none. Never blocks. */
    public String syncFriend() {
        synchronized (syncLock) {
            return syncFriend;
        }
    }

    /** Never null, never blocks. */
    public SyncReport syncReport() {
        synchronized (syncLock) {
            return syncCurrent;
        }
    }

    /** Bumped only when {@link #syncReport()} actually changed. */
    public long syncRevision() {
        return syncRevision.get();
    }

    /**
     * The Cubeon players the launcher knows, as of the last poll. Never null,
     * never blocks; empty until the launcher answers (or if it predates the
     * route).
     */
    public List<CubeonPlayer> players() {
        return players;
    }

    /** Bumped only when {@link #players()} actually changed. */
    public long playersRevision() {
        return playersRevision.get();
    }

    /**
     * The third-party poll stream: the launcher's /players route. A null body
     * means an older launcher with no route - not an error, the list is simply
     * left as it was (empty on the very first polls).
     */
    private void refreshPlayers() {
        String body = get("/players");
        if (body == null) {
            return;
        }
        List<CubeonPlayer> fresh = parsePlayers(body);
        if (!fresh.equals(players)) {
            players = fresh;
            playersRevision.incrementAndGet();
        }
    }

    /**
     * Opens (or closes, with an empty name) the Sync view for one friend. Only
     * starts the poll stream - the compare itself is
     * {@link #startSync(String)}, so opening the view costs no relay traffic
     * until the player asks for it.
     */
    public void setSyncFriend(String friend) {
        String next = friend == null ? "" : friend;
        synchronized (syncLock) {
            if (!next.equals(syncFriend)) {
                syncFriend = next;
                publishSyncLocked(next.isEmpty() ? SyncReport.NONE
                        : new SyncReport(next, "", "", false, "", "", 0, "", "", 0,
                                true, true, 0, 0, false, 0, 0, false, List.of()));
                wake();
            }
        }
    }

    /**
     * While a {@link CubeonClientScreen} is open it takes notice delivery, so
     * an error reaches the player from a menu too. Call with null on close.
     */
    public void setScreenToastSink(Consumer<Toast> sink) {
        this.screenToastSink = sink;
    }

    private void pollLoop() {
        while (true) {
            try {
                refresh();
            } catch (Throwable ex) {
                // A poll must never kill this thread: a dead poller leaves the
                // screen frozen on its last snapshot with no way to recover.
                publish(down("Cubeon bridge error: " + ex));
            }
            long wait = current.launcherUp()
                    ? (viewers.get() > 0 ? ACTIVE_POLL_MS : IDLE_POLL_MS)
                    : DOWN_BACKOFF_MS[Math.min(downStreak, DOWN_BACKOFF_MS.length - 1)];
            synchronized (wakeLock) {
                if (!wakeRequested) {
                    try {
                        wakeLock.wait(wait);
                    } catch (InterruptedException ie) {
                        Thread.currentThread().interrupt();
                        return;
                    }
                }
                wakeRequested = false;
            }
        }
    }

    private void refresh() {
        if (!loadToken()) {
            publish(down("Cubeon launcher isn't running."));
            return;
        }
        String friendsBody = get("/friends");
        if (friendsBody == null) {
            // The token file exists but nobody answered: it is stale, left by a
            // launcher that has since quit. Force a re-read next time round.
            tokenStamp = -1;
            publish(down("Cubeon launcher isn't running."));
            return;
        }
        String statusBody = get("/status");
        downStreak = 0;
        Snapshot snap = parseSnapshot(friendsBody, statusBody);
        publish(snap);
        checkModFreshness(snap);
        drainEvents();
        refreshChat();
        refreshSync();
        refreshPlayers();
    }

    /**
     * The stale-jar tripwire. The launcher fingerprints the jar it WOULD
     * install; we fingerprint the jar we are actually running from. A
     * mismatch means Cubeon was updated while this Minecraft session kept
     * the old mod - the exact "I fixed that, why am I still seeing it?"
     * confusion - so say so, once, in chat.
     */
    private void checkModFreshness(Snapshot snap) {
        if (staleWarned) {
            return;
        }
        String expected = snap.modStamp();
        if (expected == null || expected.isEmpty()) {
            return;   // older launcher, or no jar on disk - nothing to compare
        }
        String mine = ownStamp();
        if (mine.isEmpty() || mine.equals(expected)) {
            return;
        }
        staleWarned = true;
        Consumer<Toast> sink = screenToastSink != null ? screenToastSink : toastSink;
        if (sink != null) {
            sink.accept(new Toast(-2,
                    "Cubeon was updated - restart Minecraft to get the "
                            + "latest Friends features.",
                    true));
        }
    }

    /** Short sha256 of this mod's own jar, computed once. "" when unknowable
     *  (dev run from a directory, special classloaders) - the check then
     *  stays silent rather than guessing. */
    private String ownStamp() {
        if (ownStamp != null) {
            return ownStamp;
        }
        ownStamp = "";
        try {
            Object source = Bridge.class.getProtectionDomain().getCodeSource().getLocation();
            java.net.URL url = (java.net.URL) source;
            if (!"file".equals(url.getProtocol())) {
                return ownStamp;
            }
            java.io.File jar = new java.io.File(url.toURI());
            java.security.MessageDigest digest =
                    java.security.MessageDigest.getInstance("SHA-256");
            try (java.io.InputStream in = new java.io.FileInputStream(jar)) {
                byte[] buf = new byte[65536];
                int n;
                while ((n = in.read(buf)) > 0) {
                    digest.update(buf, 0, n);
                }
            }
            StringBuilder hex = new StringBuilder();
            for (byte b : digest.digest()) {
                hex.append(String.format("%02x", b));
            }
            ownStamp = hex.substring(0, 8);
        } catch (Throwable ex) {
            ownStamp = "";   // can't fingerprint - the check stays silent
        }
        return ownStamp;
    }

    private Snapshot down(String problem) {
        downStreak++;
        return new Snapshot(false, false, true, "", List.of(), List.of(), List.of(),
                Session.NONE, problem, "");
    }

    private void publish(Snapshot next) {
        if (!next.equals(current)) {
            current = next;
            revision.incrementAndGet();
        }
    }

    // ---- parsing (pure - unit tested) ------------------------------------

    /**
     * Builds a snapshot from the two GET bodies.
     *
     * <p>Every field is optional. A launcher older than this jar answers
     * {@code /friends} without {@code connected}/{@code available} and has no
     * {@code /events} at all; the defaults below make that degrade to "no
     * notifications" rather than "everything looks offline".
     */
    static Snapshot parseSnapshot(String friendsBody, String statusBody) {
        Map<String, Object> root = Json.parseObject(friendsBody);
        List<Friend> friends = new ArrayList<>();
        for (Object item : Json.list(root, "friends")) {
            String name = Json.str(item, "name", "");
            if (name.isEmpty()) {
                continue;
            }
            friends.add(new Friend(
                    name,
                    Json.bool(item, "online", false),
                    Json.str(item, "version", ""),
                    Json.str(item, "status", ""),
                    Json.bool(item, "invited", false),
                    Json.bool(item, "whitelisted", false)));
        }
        // Online first, then alphabetical - the same ordering the launcher's
        // roster used, so the two lists read identically.
        friends.sort((a, b) -> {
            if (a.online() != b.online()) {
                return a.online() ? -1 : 1;
            }
            return a.name().toLowerCase(Locale.ROOT)
                    .compareTo(b.name().toLowerCase(Locale.ROOT));
        });
        return new Snapshot(
                true,
                Json.bool(root, "connected", true),
                Json.bool(root, "available", true),
                Json.str(root, "you", ""),
                List.copyOf(friends),
                Json.strings(root, "requests_in"),
                Json.strings(root, "requests_out"),
                parseSession(statusBody),
                "",
                // Empty from an older launcher - the freshness check is
                // simply skipped, exactly as before this field existed.
                Json.str(root, "mod_stamp", ""));
    }

    static Session parseSession(String statusBody) {
        Map<String, Object> s = Json.parseObject(statusBody);
        String state = Json.str(s, "state", "");
        if (state.isEmpty()) {
            return Session.NONE;
        }
        return new Session(
                state,
                Json.str(s, "peer", ""),
                Json.str(s, "error", ""),
                Json.bool(s, "is_host", false),
                Json.str(s, "quality", ""),
                Json.bool(s, "can_retry", false));
    }

    /** Reads an /events body; returns the new cursor via {@code cursorOut[0]}. */
    static List<Toast> parseEvents(String body, long[] cursorOut) {
        Map<String, Object> root = Json.parseObject(body);
        double cursor = Json.num(root, "cursor");
        if (!Double.isNaN(cursor)) {
            cursorOut[0] = (long) cursor;
        }
        List<Toast> out = new ArrayList<>();
        for (Object item : Json.list(root, "events")) {
            String text = Json.str(item, "text", "");
            if (text.isEmpty()) {
                continue;
            }
            double seq = Json.num(item, "seq");
            out.add(new Toast(Double.isNaN(seq) ? 0L : (long) seq, text,
                    Json.bool(item, "error", false)));
        }
        return out;
    }

    /**
     * Parses one /players body. Every field is optional and every entry is
     * checked: a launcher that changed shape must degrade to fewer rows, never
     * an exception on the poll thread.
     */
    static List<CubeonPlayer> parsePlayers(String body) {
        Map<String, Object> root = Json.parseObject(body);
        List<CubeonPlayer> out = new ArrayList<>();
        for (Object item : Json.list(root, "players")) {
            String name = Json.str(item, "name", "");
            if (name.isEmpty()) {
                continue;
            }
            out.add(new CubeonPlayer(
                    name,
                    Json.bool(item, "online", false),
                    Json.str(item, "skin", ""),
                    Json.str(item, "cape", ""),
                    Json.str(item, "version", ""),
                    Json.str(item, "status", "")));
        }
        out.sort((a, b) -> {
            if (a.online() != b.online()) {
                return a.online() ? -1 : 1;
            }
            return a.name().toLowerCase(Locale.ROOT)
                    .compareTo(b.name().toLowerCase(Locale.ROOT));
        });
        return List.copyOf(out);
    }

    private void drainEvents() {
        String body = get("/events?since=" + eventCursor);
        if (body == null) {
            return;   // an older launcher has no /events - not an error
        }
        long[] cursorOut = {eventCursor};
        List<Toast> toasts = parseEvents(body, cursorOut);
        eventCursor = cursorOut[0];
        // A notice while the Friends screen is open goes to its status line;
        // the overlay sink needs a live player and is invisible from a menu.
        Consumer<Toast> sink = screenToastSink != null ? screenToastSink : toastSink;
        if (sink == null) {
            return;
        }
        for (Toast toast : toasts) {
            sink.accept(toast);
        }
    }

    /**
     * The second poll stream. Only runs while a chat partner is set, so an
     * idle screen costs the launcher nothing extra. A body of null means an
     * older launcher with no /chat - not an error, the conversation is simply
     * left as it was.
     */
    private void refreshChat() {
        String friend;
        long cursor;
        synchronized (chatLock) {
            friend = chatFriend;
            cursor = chatCursor;
        }
        if (friend == null || friend.isEmpty()) {
            return;
        }
        String body = get("/chat?friend=" + friend + "&after=" + cursor);
        if (body == null) {
            return;
        }
        long[] cursorOut = {cursor};
        List<ChatMessage> fresh = parseChatMessages(body, cursorOut);
        synchronized (chatLock) {
            // A friend switch could have happened between the GET and this
            // merge; the reply for the old friend must not land in the new
            // conversation.
            if (!friend.equals(chatFriend)) {
                return;
            }
            if (cursor < 0) {
                // First page: the launcher answered with the whole recent
                // window, so it replaces the transcript outright.
                chatCursor = cursorOut[0];
                publishChatLocked(new ChatConversation(friend, keepFresh(fresh)));
                return;
            }
            List<ChatMessage> merged = new ArrayList<>(chatCurrent.messages());
            for (ChatMessage message : fresh) {
                if (message.seq() > chatCursor) {
                    merged.add(message);
                }
            }
            long last = cursorOut[0];
            if (last > chatCursor) {
                chatCursor = last;
            }
            publishChatLocked(new ChatConversation(friend, keepFresh(merged)));
        }
    }

    private static List<ChatMessage> keepFresh(List<ChatMessage> messages) {
        int size = messages.size();
        if (size <= CHAT_KEEP) {
            return List.copyOf(messages);
        }
        return List.copyOf(messages.subList(size - CHAT_KEEP, size));
    }

    private void publishChatLocked(ChatConversation next) {
        if (!next.equals(chatCurrent)) {
            chatCurrent = next;
            chatRevision.incrementAndGet();
        }
    }

    /**
     * Parses one /chat body into transcript lines, advancing {@code cursorOut}
     * to the newest seq it contains. Every field is optional: a launcher older
     * than this jar, or one that has changed shape, must degrade to an empty
     * page, never an exception on the poll thread.
     */
    static List<ChatMessage> parseChatMessages(String body, long[] cursorOut) {
        Map<String, Object> root = Json.parseObject(body);
        List<ChatMessage> out = new ArrayList<>();
        long last = cursorOut != null && cursorOut.length > 0 ? cursorOut[0] : -1;
        for (Object item : Json.list(root, "messages")) {
            double seq = Json.num(item, "seq");
            if (Double.isNaN(seq)) {
                continue;
            }
            String text = Json.str(item, "text", "");
            if (text.isEmpty()) {
                continue;
            }
            long s = (long) seq;
            boolean incoming = !"out".equals(Json.str(item, "dir", ""));
            out.add(new ChatMessage(s, incoming, Json.str(item, "name", ""), text));
            last = Math.max(last, s);
        }
        if (cursorOut != null && cursorOut.length > 0) {
            cursorOut[0] = last;
        }
        return out;
    }

    /**
     * The third poll stream. Only runs while a Sync friend is set. A null body
     * means an older launcher with no /sync - the report is left as it was
     * rather than flipped to an error, so the view degrades to "nothing here"
     * instead of accusing the launcher of breaking.
     */
    private void refreshSync() {
        String friend;
        synchronized (syncLock) {
            friend = syncFriend;
        }
        if (friend == null || friend.isEmpty()) {
            return;
        }
        String body = get("/sync?friend=" + friend);
        if (body == null) {
            return;
        }
        SyncReport fresh = parseSyncReport(friend, body);
        synchronized (syncLock) {
            // The player may have closed the view (or switched friend) between
            // the GET and here; that reply must not land in the new one.
            if (!friend.equals(syncFriend)) {
                return;
            }
            publishSyncLocked(fresh);
        }
    }

    private void publishSyncLocked(SyncReport next) {
        if (!next.equals(syncCurrent)) {
            syncCurrent = next;
            syncRevision.incrementAndGet();
        }
    }

    /**
     * Parses one /sync body. Every field is optional and defaults to the
     * harmless reading ("compatible, nothing to download"), so a launcher older
     * or newer than this jar can never make the view claim an incompatibility
     * it didn't actually report.
     */
    static SyncReport parseSyncReport(String friend, String body) {
        Map<String, Object> root = Json.parseObject(body);
        List<String> lines = Json.strings(root, "lines");
        Object you = root.get("you");
        Object them = root.get("them");
        return new SyncReport(
                friend,
                Json.str(root, "state", "idle"),
                Json.str(root, "error", ""),
                Json.bool(root, "encrypted", false),
                Json.str(you, "version", ""),
                Json.str(you, "loader", ""),
                intOf(you, "mods"),
                Json.str(them, "version", ""),
                Json.str(them, "loader", ""),
                intOf(them, "mods"),
                Json.bool(root, "version_ok", true),
                Json.bool(root, "loader_ok", true),
                Json.list(root, "missing").size(),
                Json.list(root, "extra").size(),
                Json.bool(root, "can_download", false),
                intOf(root, "download_done"),
                intOf(root, "download_total"),
                Json.bool(root, "needs_relaunch", false),
                lines);
    }

    private static int intOf(Object holder, String key) {
        double v = Json.num(holder, key);
        return Double.isNaN(v) ? 0 : (int) v;
    }

    // ---- actions ---------------------------------------------------------
    // All of these block on the network and MUST be called from a worker
    // thread, never from render/init. CubeonClientScreen.submit() is the only
    // caller and it always uses one.


    public Result invite(String name) {
        return post("/invite", Json.object("name", name));
    }

    public Result join(String name) {
        return post("/join", Json.object("name", name));
    }

    public Result addFriend(String name) {
        return post("/add", Json.object("name", name));
    }

    public Result acceptRequest(String name) {
        return post("/accept", Json.object("name", name));
    }

    public Result declineRequest(String name) {
        return post("/decline", Json.object("name", name));
    }

    public Result removeFriend(String name) {
        return post("/remove", Json.object("name", name));
    }

    public Result rename(String name) {
        return post("/rename", Json.object("name", name));
    }

    public Result setWhitelisted(String name, boolean on) {
        return post("/whitelist", Json.object("name", name, "on", on));
    }

    public Result sendChat(String friend, String text) {
        return post("/dm", Json.object("to", friend, "text", text));
    }

    /** Opens the profile compare with a friend. Answers immediately; the report
     *  arrives on the next {@link #refreshSync()} poll. */
    public Result startSync(String name) {
        return post("/syncstart", Json.object("name", name));
    }

    /** Pulls the mods this machine is missing into the global mods store. */
    public Result downloadMods(String name) {
        return post("/syncdownload", Json.object("name", name));
    }

    /** Drops the compare room so the relay isn't holding one open. */
    public Result closeSync(String name) {
        return post("/syncclose", Json.object("name", name));
    }

    /** Asks a friend to open their world to us - the other half of Play. */
    public Result askToJoin(String name) {
        return post("/askjoin", Json.object("name", name));
    }

    public Result cancelSession() {
        return post("/cancel", "{}");
    }

    /** The host's world-password decision: a non-empty password arms the
     *  gate, an empty one skips it (the launcher treats "" as Skip). The
     *  invite only rings out after this. */
    public Result setWorldGate(String password) {
        return post("/worldgate", Json.object("password", password == null ? "" : password));
    }

    /** The joiner's answer to the host's password challenge. */
    public Result sendJoinPassword(String password) {
        return post("/joinpassword", Json.object("password", password));
    }

    public Result retrySession() {
        return post("/retry", "{}");
    }

    // ---- transport -------------------------------------------------------

    /**
     * Reads ~/.cubeon_launcher/local_api.json when it is new or has changed.
     * Returns false when there is nothing to talk to.
     */
    private boolean loadToken() {
        try {
            long stamp = Files.getLastModifiedTime(TOKEN_FILE).toMillis();
            if (stamp == tokenStamp && token != null) {
                return true;
            }
            Map<String, Object> conf = Json.parseObject(
                    Files.readString(TOKEN_FILE, StandardCharsets.UTF_8));
            double port = Json.num(conf, "port");
            String tok = Json.str(conf, "token", "");
            if (Double.isNaN(port) || port <= 0 || tok.isEmpty()) {
                return false;
            }
            baseUrl = "http://127.0.0.1:" + (int) port;
            token = tok;
            tokenStamp = stamp;
            return true;
        } catch (IOException | RuntimeException ex) {
            token = null;
            tokenStamp = -1;
            return false;
        }
    }

    /** Response body, or null for any failure at all. */
    private String get(String path) {
        if (token == null) {
            return null;
        }
        try {
            HttpRequest request = HttpRequest.newBuilder(URI.create(baseUrl + path))
                    .timeout(READ_TIMEOUT)
                    .header("X-Cubeon-Token", token)
                    .GET()
                    .build();
            HttpResponse<String> response = http.send(request,
                    HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            return response.statusCode() == 200 ? response.body() : null;
        } catch (InterruptedException ie) {
            Thread.currentThread().interrupt();
            return null;
        } catch (Exception ex) {
            return null;
        }
    }

    private Result post(String path, String body) {
        if (!loadToken()) {
            return Result.fail("The Cubeon launcher isn't running.");
        }
        try {
            HttpRequest request = HttpRequest.newBuilder(URI.create(baseUrl + path))
                    .timeout(ACTION_TIMEOUT)
                    .header("X-Cubeon-Token", token)
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(body, StandardCharsets.UTF_8))
                    .build();
            HttpResponse<String> response = http.send(request,
                    HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            Result result = readResult(response.statusCode(), response.body());
            wake();   // reflect the change in the roster without waiting for a poll
            return result;
        } catch (InterruptedException ie) {
            Thread.currentThread().interrupt();
            return Result.fail("Interrupted.");
        } catch (Exception ex) {
            return Result.fail("Couldn't reach the Cubeon launcher.");
        }
    }

    /**
     * Turns a launcher response into a Result.
     *
     * <p>Two shapes exist and both are honoured: the bridge's own
     * {@code {"ok":false,"error":...}} and friends.claim()'s
     * {@code {"ok":false,"message":...}}, which /rename relays verbatim. Losing
     * the second one is how a rejected rename used to surface as the generic
     * "Couldn't change the name" instead of the actual reason.
     */
    static Result readResult(int statusCode, String body) {
        Map<String, Object> root = Json.parseObject(body);
        if (Json.bool(root, "ok", false)) {
            return Result.OK;
        }
        String error = Json.str(root, "error", "");
        if (error.isEmpty()) {
            error = Json.str(root, "message", "");
        }
        if (!error.isEmpty()) {
            return Result.fail(error);
        }
        if (statusCode == 401) {
            return Result.fail("The launcher rejected this session's token. Restart Cubeon.");
        }
        if (statusCode == 404) {
            return Result.fail("Your Cubeon launcher is older than this mod - update it.");
        }
        return Result.fail("The launcher couldn't do that (HTTP " + statusCode + ").");
    }

    // ---- shared name rules ----------------------------------------------

    /**
     * A fast local check so an obviously bad name never costs a round trip.
     *
     * <p>Only length and character class, on purpose. The launcher's
     * friends.validate_name() also rejects a list of reserved names, and
     * duplicating that list here would let the two drift - so anything passing
     * this check is sent, and the launcher's own message is what gets shown.
     *
     * @return null when acceptable, else the reason.
     */
    public static String checkName(String name) {
        if (name == null || name.isEmpty()) {
            return "Type a name first.";
        }
        if (name.length() < 3) {
            return "Names need at least 3 characters.";
        }
        if (name.length() > 16) {
            return "Names can be at most 16 characters.";
        }
        for (int i = 0; i < name.length(); i++) {
            char c = name.charAt(i);
            boolean allowed = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z')
                    || (c >= '0' && c <= '9') || c == '_';
            if (!allowed) {
                return "Letters, numbers and underscores only.";
            }
        }
        return null;
    }
}
