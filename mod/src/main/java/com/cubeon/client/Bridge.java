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
import java.util.concurrent.atomic.AtomicLong;
import java.util.function.Consumer;

/**
 * Everything this mod knows about the launcher, and the only thing that talks
 * to it.
 *
 * <p>The launcher owns the friends account, the roster and the chat store
 * (see cubeon/friends_service.py); it publishes them over
 * a token-authenticated HTTP API bound to 127.0.0.1 (cubeon/local_api.py). This
 * class polls that API on ONE daemon thread and publishes an immutable
 * {@link Snapshot}, which the screen reads without ever blocking.
 *
 * <p>That split is the fix for the mod's worst bug rather than a style choice.
 * The screen used to call blocking launch-bridge lookups straight from
 * {@code Screen.init()} - blocking HTTP round trips, each up to 1.5s, on
 * the render thread. Opening the pause menu could therefore freeze Minecraft
 * for several seconds, and resizing the window did it all over again.
 *
 * <p>Deliberately contains NO Minecraft imports: it is plain Java, so it
 * compiles and unit-tests against a bare JDK (mod/tools/SelfTest.java) and
 * carries no dependency on any particular Minecraft version.
 */
public final class Bridge {

    /** Polling period - just enough to catch notifications without cost. */
    private static final long IDLE_POLL_MS = 6_000;
    /** Backoff steps used while the launcher looks absent. */
    private static final long[] DOWN_BACKOFF_MS = {1_000, 2_000, 4_000, 8_000};

    private static final Duration CONNECT_TIMEOUT = Duration.ofMillis(900);
    private static final Duration READ_TIMEOUT = Duration.ofMillis(2_000);
    // A big download or a pack install can keep the launcher's HTTP thread
    // busy past the normal 2 s; the friends screen must not flicker offline
    // for that. Only /friends gets this longer read (it is the poll that
    // decides "is the launcher up").
    private static final Duration FRIENDS_READ_TIMEOUT = Duration.ofSeconds(5);

    /** Consecutive unanswered polls before the UI is told the launcher is
     *  down. One slow or failed reply keeps the last snapshot. */
    static final int DOWN_STREAK_FOR_DOWN = 3;
    /**
     * POST /invite etc. can block on a launcher REST round trip, so they get
     * a generous budget.
     *
     * <p>30s, not 15: the launcher's slowest action (a server-side claim
     * round trip, on a 15s budget) used to be reachable from here, and a 15s
     * limit could time out an action that was about to succeed and report
     * "Couldn't reach the Cubeon launcher" for a rename that actually landed.
     * Every ordinary POST answers in microseconds; the slack costs nothing.
     */
    private static final Duration ACTION_TIMEOUT = Duration.ofSeconds(30);

    /** Keep a malformed local response from becoming an unbounded JSON parse. */
    private static final int MAX_RESPONSE_CHARS = 1_000_000;
    /** The launcher currently writes a short URL-safe token; cap corrupt files. */
    private static final int MAX_TOKEN_CHARS = 256;


    private static final Path TOKEN_FILE = Path.of(
            System.getProperty("user.home", "."), ".cubeon_launcher", "local_api.json");

    private static Bridge instance;

    // ---- value types -----------------------------------------------------

    /** One roster entry, exactly as the launcher's Friends list showed it. */
    public record Friend(String name, boolean online, String version, String status,
                         boolean invited, boolean whitelisted, String uid,
                         String minecraftUsername) {

        public Friend(String name, boolean online, String version, String status,
                      boolean invited, boolean whitelisted) {
            this(name, online, version, status, invited, whitelisted, "", "");
        }

        public String displayName() {
            return safeName(minecraftUsername, uid);
        }

        public String label() {
            return identityLabel(minecraftUsername, uid);
        }

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

    /**
     * One consistent picture of the launcher. Immutable and compared by value,
     * so the screen can rebuild its widgets only when something really changed
     * rather than on every single poll.
     */
    public record Snapshot(boolean launcherUp, boolean connected, boolean available,
                           String you, String youUid, List<Friend> friends,
                           String problem,
                           String modStamp, String youMinecraftUsername) {

        public static final Snapshot DOWN = new Snapshot(
                false, false, true, "", "", List.of(),
                "Looking for the Cubeon launcher...", "", "");

        public String youDisplayName() {
            return safeName(youMinecraftUsername, youUid);
        }

        public Peer peer(String handle) {
            for (Friend friend : friends) {
                if (friend.name().equals(handle)) {
                    return new Peer(handle, friend.uid(), friend.minecraftUsername());
                }
            }
            return new Peer(handle, "", "");
        }

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

        /** The header line: whether presence is flowing. The account's NAME
         * is deliberately not part of this line - the account is the Cubeon
         * ID (youUid); the visible name is just the player's Minecraft
         * username, which the screen shows in friend/session details. The old
         * "Connected as <claimed-name>" advertised the
         * relay's internal handle, which is exactly the identity confusion
         * the UID system exists to remove. */
        public String connectionLine() {
            if (!launcherUp) {
                return "Cubeon launcher not found";
            }
            if (!available) {
                return "Realtime add-on missing in the launcher";
            }
            if (!claimed()) {
                return "Cubeon account not set up yet";
            }
            return connected ? "Connected to Cubeon"
                             : "Offline - reconnecting...";
        }
    }

    public record Peer(String name, String uid, String minecraftUsername) {
        public String displayName() {
            return safeName(minecraftUsername, uid);
        }

        public String label() {
            return identityLabel(minecraftUsername, uid);
        }
    }

    public static String canonicalUid(Object value) {
        String text;
        if (value instanceof Number number) {
            double n = number.doubleValue();
            if (!Double.isFinite(n) || n != Math.floor(n) || n < 0 || n > 99999999L) {
                return "";
            }
            text = Long.toString((long) n);
        } else {
            text = value instanceof String s ? s.trim() : "";
        }
        if (!text.matches("[0-9]{1,8}")) return "";
        return "0".repeat(8 - text.length()) + text;
    }

    public static String minecraftUsername(String value) {
        return value != null && value.matches("[A-Za-z0-9_]{3,16}") ? value : "";
    }

    public static String safeName(String username, String uid) {
        String valid = minecraftUsername(username);
        String id = canonicalUid(uid);
        return !valid.isEmpty() ? valid : !id.isEmpty() ? "Cubeon ID " + id : "Player";
    }

    public static String identityLabel(String username, String uid) {
        String label = safeName(username, uid);
        String id = canonicalUid(uid);
        return minecraftUsername(username).isEmpty() || id.isEmpty()
                ? label : label + " (" + id + ")";
    }

    private static String uidOf(Object holder, String key) {
        return holder instanceof Map<?, ?> map ? canonicalUid(map.get(key)) : "";
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
                               String version, String status, String uid, String minecraftUsername) {

        public String displayName() {
            return safeName(minecraftUsername, uid);
        }

        public String label() {
            return identityLabel(minecraftUsername, uid);
        }

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

    // ---- state -----------------------------------------------------------

    private final HttpClient http = HttpClient.newBuilder()
            .connectTimeout(CONNECT_TIMEOUT)
            .followRedirects(HttpClient.Redirect.NEVER)
            .build();

    private final Object wakeLock = new Object();
    private final AtomicLong revision = new AtomicLong();

    private volatile Snapshot current = Snapshot.DOWN;
    private volatile Consumer<Toast> toastSink;
    private volatile Thread poller;

    private boolean wakeRequested;

    // ---- players state ----------------------------------------------------
    // A fourth poll stream, on the same terms as chat and sync: the launcher's
    // /players route. Unlike the other two it is not opened and closed by a
    // view - it is cheap (one localhost GET) and the Online panel, the Profile
    // view and the nametag badge all read it, so it rides along on every
    // roster poll. An older launcher has no route at all; the empty list that
    // degrades to is the correct answer for every reader.
    private final AtomicLong playersRevision = new AtomicLong();
    private volatile List<CubeonPlayer> players = List.of();

    // Poll state is single-threaded; token fields are volatile because POST
    // actions may invalidate credentials from their worker threads.
    private volatile String baseUrl;
    private volatile String token;
    private volatile long tokenStamp = -1;
    private volatile long tokenSize = -1;
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

    /** Where launcher notifications are delivered. Called on the poll thread. */
    public void setToastSink(Consumer<Toast> sink) {
        this.toastSink = sink;
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

    private void pollLoop() {
        try {
            while (true) {
                try {
                    refresh();
                } catch (RuntimeException ex) {
                    // A malformed response or callback must not kill this
                    // thread: a dead poller leaves the screen frozen on its
                    // last snapshot with no way to recover. VM errors and
                    // thread termination are deliberately not swallowed.
                    publish(down("Cubeon bridge error: " + ex));
                }
                long wait = current.launcherUp()
                        ? IDLE_POLL_MS
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
        } finally {
            // If the thread is interrupted or an unrecoverable error reaches
            // here, a later screen is still allowed to start a fresh poller.
            synchronized (this) {
                if (poller == Thread.currentThread()) {
                    poller = null;
                }
            }
        }
    }

    private void refresh() {
        if (!loadToken()) {
            publish(down("Cubeon launcher isn't running."));
            return;
        }
        Reply friends = getReply("/friends");
        if (!friends.isOk()) {
            // Only a refused connection (or a rejected token) proves the
            // launcher is gone. A timeout or a 5xx while it is busy just means
            // "no answer yet": keep the last snapshot and retry, and only tell
            // the player it is down after several polls in a row. Treating
            // every slow reply as "down" is what made the Friends screen
            // flicker offline during a download and reset its backoff.
            downStreak += 1;
            if (provesLauncherGone(friends) || downStreak >= DOWN_STREAK_FOR_DOWN) {
                if (provesLauncherGone(friends)) {
                    // The token file exists but nobody is listening (or it was
                    // rejected): force a re-read next poll.
                    invalidateToken();
                }
                publish(down("Cubeon launcher isn't running."));
            }
            return;
        }
        downStreak = 0;
        Snapshot snap = parseSnapshot(friends.body);
        publish(snap);
        // Each follow-up poll is independent. A malformed /events or /players
        // body used to propagate to pollLoop and publish "Cubeon bridge error"
        // for a launcher that had just answered /friends, and skipped the rest
        // of that poll; keep the last data and retry next round instead.
        quietly("mod freshness", () -> checkModFreshness(snap));
        quietly("event drain", this::drainEvents);
        quietly("player refresh", this::refreshPlayers);
    }

    /** Runs one sub-step of a poll; a failure keeps the last data. */
    static void quietly(String what, Runnable step) {
        try {
            step.run();
        } catch (RuntimeException ex) {
            // Deliberately silent: the poll loop logs nothing, and the next
            // poll retries with the still-valid snapshot in place.
        }
    }

    /** True only when this reply proves nothing is listening any more.
     *  A timeout or a 5xx is "busy", not "gone". */
    static boolean provesLauncherGone(Reply reply) {
        return reply.refused || reply.status == 401;
    }

    /** Which transport failure this was, for {@link #provesLauncherGone}. */
    static Reply classifyFailure(Throwable ex) {
        for (Throwable t = ex; t != null; t = t.getCause()) {
            if (t instanceof java.net.http.HttpTimeoutException) {
                return Reply.timeout();
            }
            if (t instanceof java.net.ConnectException) {
                return Reply.refused();
            }
        }
        return Reply.failed();
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
        Consumer<Toast> sink = toastSink;
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
        return new Snapshot(false, false, true, "", "", List.of(),
                problem, "", "");
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
    static Snapshot parseSnapshot(String friendsBody) {
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
                    Json.bool(item, "whitelisted", false),
                    uidOf(item, "uid"),
                    minecraftUsername(Json.str(item, "minecraft_username", ""))));
        }
        // Online first, then alphabetical - the same ordering the launcher's
        // roster used, so the two lists read identically.
        friends.sort((a, b) -> {
            if (a.online() != b.online()) {
                return a.online() ? -1 : 1;
            }
            int labelOrder = a.label().toLowerCase(Locale.ROOT)
                    .compareTo(b.label().toLowerCase(Locale.ROOT));
            return labelOrder != 0 ? labelOrder : a.name().compareToIgnoreCase(b.name());
        });
        return new Snapshot(
                true,
                Json.bool(root, "connected", true),
                Json.bool(root, "available", true),
                Json.str(root, "you", ""),
                // The 8-digit public Cubeon ID - the account's real handle.
                // The internal claimed name above is plumbing; this is what
                // friend details show and what friends add you by.
                uidOf(root, "you_uid"),
                List.copyOf(friends),
                "",
                // Empty from an older launcher - the freshness check is
                // simply skipped, exactly as before this field existed.
                Json.str(root, "mod_stamp", ""),
                minecraftUsername(Json.str(root, "you_minecraft_username", "")));
    }

    /** Reads an /events body; returns the new cursor via {@code cursorOut[0]}. */
    static List<Toast> parseEvents(String body, long[] cursorOut) {
        Map<String, Object> root = Json.parseObject(body);
        long cursor = sequence(root, "cursor");
        // A smaller but valid cursor means the launcher restarted and its
        // in-memory event sequence reset. Accept it so notifications recover
        // instead of permanently asking the new process for events after an
        // ID it can never produce.
        if (cursor >= 0 && cursorOut != null && cursorOut.length > 0) {
            cursorOut[0] = cursor;
        }
        List<Toast> out = new ArrayList<>();
        for (Object item : Json.list(root, "events")) {
            String text = Json.str(item, "text", "");
            if (text.isEmpty()) {
                continue;
            }
            long seq = sequence(item, "seq");
            out.add(new Toast(seq < 0 ? 0L : seq, text,
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
                    Json.str(item, "status", ""),
                    uidOf(item, "uid"),
                    minecraftUsername(Json.str(item, "minecraft_username", ""))));
        }
        out.sort((a, b) -> {
            if (a.online() != b.online()) {
                return a.online() ? -1 : 1;
            }
            int labelOrder = a.label().toLowerCase(Locale.ROOT)
                    .compareTo(b.label().toLowerCase(Locale.ROOT));
            return labelOrder != 0 ? labelOrder : a.name().compareToIgnoreCase(b.name());
        });
        return List.copyOf(out);
    }

    private void drainEvents() {
        String body = get("/events?since=" + Math.max(-1, eventCursor));
        if (body == null) {
            return;   // an older launcher has no /events - not an error
        }
        long[] cursorOut = {eventCursor};
        List<Toast> toasts = parseEvents(body, cursorOut);
        eventCursor = cursorOut[0];
        Consumer<Toast> sink = toastSink;
        if (sink == null) {
            return;
        }
        for (Toast toast : toasts) {
            sink.accept(toast);
        }
    }

    /** A JSON sequence number, or -1 for missing/non-integral/out-of-range data. */
    private static long sequence(Object holder, String key) {
        double value = Json.num(holder, key);
        if (!Double.isFinite(value) || value < 0 || value != Math.floor(value)
                || value > Long.MAX_VALUE) {
            return -1;
        }
        return (long) value;
    }

    // ---- actions ---------------------------------------------------------
    // Blocks on the network and MUST be called from a worker thread, never
    // from render/init.

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

    // ---- transport -------------------------------------------------------

    /**
     * Reads ~/.cubeon_launcher/local_api.json when it is new or has changed.
     * Returns false when there is nothing to talk to.
     */
    private synchronized boolean loadToken() {
        try {
            long stamp = Files.getLastModifiedTime(TOKEN_FILE).toMillis();
            long size = Files.size(TOKEN_FILE);
            if (stamp == tokenStamp && size == tokenSize && token != null && baseUrl != null) {
                return true;
            }
            Map<String, Object> conf = Json.parseObject(
                    Files.readString(TOKEN_FILE, StandardCharsets.UTF_8));
            double port = Json.num(conf, "port");
            String tok = Json.str(conf, "token", "");
            if (!validPort(port) || !validToken(tok)) {
                invalidateToken();
                return false;
            }
            baseUrl = "http://127.0.0.1:" + (int) port;
            token = tok;
            tokenStamp = stamp;
            tokenSize = size;
            return true;
        } catch (IOException | RuntimeException ex) {
            invalidateToken();
            return false;
        }
    }

    static boolean validPort(double port) {
        return Double.isFinite(port) && port == Math.floor(port)
                && port >= 1 && port <= 65535;
    }

    private static boolean validToken(String value) {
        if (value == null || value.isBlank() || value.length() > MAX_TOKEN_CHARS) {
            return false;
        }
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            // HttpRequest rejects control characters in headers. Reject them
            // here so a corrupt token file becomes a clean offline state.
            if (c <= 0x20 || c >= 0x7f) {
                return false;
            }
        }
        return true;
    }

    private synchronized void invalidateToken() {
        token = null;
        baseUrl = null;
        tokenStamp = -1;
        tokenSize = -1;
    }

    private static boolean usableBody(String body) {
        return body != null && body.length() <= MAX_RESPONSE_CHARS;
    }

    /**
     * One GET outcome. {@code body} is null unless the request really answered;
     * {@code status} is the HTTP code (0 when there was no answer at all), so
     * "refused" and "busy" can be told apart instead of collapsing into null.
     */
    static final class Reply {
        final String body;
        final int status;
        final boolean refused;
        final boolean timedOut;

        private Reply(String body, int status, boolean refused, boolean timedOut) {
            this.body = body;
            this.status = status;
            this.refused = refused;
            this.timedOut = timedOut;
        }

        static Reply ok(String body) {
            return new Reply(body, 200, false, false);
        }

        static Reply status(int code) {
            return new Reply(null, code, false, false);
        }

        static Reply refused() {
            return new Reply(null, 0, true, false);
        }

        static Reply timeout() {
            return new Reply(null, 0, false, true);
        }

        static Reply failed() {
            return new Reply(null, 0, false, false);
        }

        boolean isOk() {
            return body != null;
        }
    }

    /** Response body, or null for any failure at all. */
    private String get(String path) {
        return getReply(path).body;
    }

    /** One GET with the failure kind preserved (see {@link Reply}). */
    private Reply getReply(String path) {
        String currentBaseUrl = baseUrl;
        String currentToken = token;
        if (currentBaseUrl == null || currentToken == null) {
            return Reply.refused();   // nothing to talk to yet
        }
        try {
            HttpRequest request = HttpRequest.newBuilder(URI.create(currentBaseUrl + path))
                    .timeout(path.startsWith("/friends") ? FRIENDS_READ_TIMEOUT : READ_TIMEOUT)
                    .header("X-Cubeon-Token", currentToken)
                    .GET()
                    .build();
            HttpResponse<String> response = http.send(request,
                    HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.statusCode() == 401) {
                invalidateToken();
                return Reply.status(401);
            }
            if (response.statusCode() >= 200 && response.statusCode() < 300
                    && usableBody(response.body())) {
                return Reply.ok(response.body());
            }
            return Reply.status(response.statusCode());
        } catch (InterruptedException ie) {
            Thread.currentThread().interrupt();
            return Reply.failed();
        } catch (Exception ex) {
            return classifyFailure(ex);
        }
    }

    private Result post(String path, String body) {
        if (!loadToken()) {
            return Result.fail("The Cubeon launcher isn't running.");
        }
        String currentBaseUrl = baseUrl;
        String currentToken = token;
        if (currentBaseUrl == null || currentToken == null) {
            return Result.fail("The Cubeon launcher isn't running.");
        }
        try {
            HttpRequest request = HttpRequest.newBuilder(URI.create(currentBaseUrl + path))
                    .timeout(ACTION_TIMEOUT)
                    .header("X-Cubeon-Token", currentToken)
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(body == null ? "{}" : body,
                            StandardCharsets.UTF_8))
                    .build();
            HttpResponse<String> response = http.send(request,
                    HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.statusCode() == 401) {
                invalidateToken();
            }
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
        Map<String, Object> root = usableBody(body) ? Json.parseObject(body) : Map.of();
        if (statusCode >= 200 && statusCode < 300 && Json.bool(root, "ok", false)) {
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
        if (!usableBody(body)) {
            return Result.fail("The launcher returned an invalid response.");
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
