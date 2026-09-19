/*
 * Offline unit tests for the Minecraft-free half of the Cubeon Client mod.
 *
 * The mod's UI needs a real Minecraft jar to compile, but everything that has
 * ever actually been *wrong* in it lived in the plain-Java half: JSON parsing,
 * outbound escaping, roster ordering, and turning a launcher response into a
 * message a player can read. Those classes deliberately import no Minecraft, so
 * this file compiles and runs against a bare JDK - no Gradle, no network, no
 * Minecraft install.
 *
 * Run it through tools/test_mod_bridge.py, or by hand:
 *   javac -d /tmp/out mod/src/main/java/com/cubeon/client/{Json,Bridge}.java \
 *         mod/tools/SelfTest.java
 *   java -cp /tmp/out com.cubeon.client.SelfTest
 *
 * <p>It declares the production package on purpose: the response parsers are
 * package-private because nothing outside Bridge should call them, and a test
 * is not a reason to widen an API. It lives outside src/main/java, so Gradle
 * never compiles it into the shipped jar.
 */
package com.cubeon.client;

import java.util.List;
import java.util.Map;

public final class SelfTest {

    private static int passed;
    private static int failed;

    public static void main(String[] args) {
        jsonParsing();
        jsonEscaping();
        snapshotParsing();
        rosterOrdering();
        theOldParsingBugs();
        sessionParsing();
        eventParsing();
        chatParsing();
        playersParsing();
        resultReading();
        uidAndPortRules();
        nameChecking();
        presenceText();
        connectionText();

        System.out.println();
        System.out.println(passed + " passed, " + failed + " failed");
        if (failed > 0) {
            System.exit(1);
        }
    }

    // ---- Json ------------------------------------------------------------

    private static void jsonParsing() {
        section("Json: parsing");
        Map<String, Object> o = Json.parseObject(
                "{\"a\": 1, \"b\": \"two\", \"c\": true, \"d\": null, \"e\": [1, 2], "
                        + "\"f\": {\"g\": -3.5e2}}");
        ok(Json.num(o, "a") == 1.0, "integer");
        ok("two".equals(Json.str(o, "b", "")), "string");
        ok(Json.bool(o, "c", false), "true");
        ok(Json.str(o, "d", "fallback").equals("fallback"), "null falls back");
        ok(Json.list(o, "e").size() == 2, "array");
        ok(Json.num(Json.parseObject("{\"g\": -3.5e2}"), "g") == -350.0, "exponent number");

        ok(Double.isNaN(Json.num(o, "missing")), "absent number is NaN");
        ok(Json.list(o, "missing").isEmpty(), "absent array is empty");
        ok(!Json.bool(o, "missing", false), "absent bool falls back");

        // Wrong-typed reads must fall back rather than throw: screen code has
        // no try/catch and a launcher schema change must not crash the client.
        ok(Json.str(o, "a", "fallback").equals("fallback"), "number read as string falls back");
        ok(Json.list(o, "b").isEmpty(), "string read as array falls back");
        ok(Json.num(o, "b") != Json.num(o, "b") /* NaN */, "string read as number is NaN");

        ok(Json.parseObject("not json at all").isEmpty(), "garbage -> empty map");
        ok(Json.parseObject("[1,2,3]").isEmpty(), "top-level array -> empty map");
        ok(Json.parseObject("").isEmpty(), "empty body -> empty map");
        ok(Json.parseObject(null).isEmpty(), "null body -> empty map");
        ok(Json.parseObject("{\"a\":1} trailing").isEmpty(), "trailing content refused");
        ok(Json.parseObject("{\"a\":").isEmpty(), "truncated object refused");

        String deep = "{\"a\":".repeat(80) + "1" + "}".repeat(80);
        ok(Json.parseObject(deep).isEmpty(), "excessive nesting refused, not a stack overflow");

        Map<String, Object> esc = Json.parseObject(
                "{\"s\": \"line\\nbreak \\\"quoted\\\" back\\\\slash \\u0041\\t\"}");
        ok(Json.str(esc, "s", "").equals("line\nbreak \"quoted\" back\\slash A\t"),
                "every escape sequence decoded");

        ok(Json.strings(Json.parseObject("{\"r\": [\"a\", 5, \"\", null, \"b\"]}"), "r")
                .equals(List.of("a", "b")),
                "strings() keeps only non-empty strings");
    }

    private static void jsonEscaping() {
        section("Json: writing");
        ok(Json.quote("plain").equals("\"plain\""), "plain name");
        // The bug this replaced: the mod used name.replace("\"", ""), so a
        // trailing backslash escaped the closing quote and the launcher saw a
        // malformed body instead of a name.
        ok(Json.quote("ends_with\\").equals("\"ends_with\\\\\""), "trailing backslash escaped");
        ok(Json.quote("say\"hi").equals("\"say\\\"hi\""), "embedded quote escaped");
        ok(Json.quote("a\nb").equals("\"a\\nb\""), "newline escaped");
        ok(Json.quote("ab").equals("\"a\\u0001b\""), "control character escaped");
        ok(Json.quote(null).equals("\"\""), "null name -> empty string, not \"null\"");

        // Round trip: whatever we send must come back as the same characters.
        String nasty = "we\\ird\"na\nme";
        Map<String, Object> back = Json.parseObject(Json.object("name", nasty));
        ok(nasty.equals(Json.str(back, "name", "")), "quote() output re-parses identically");

        ok(Json.object("name", "Ali", "on", true).equals("{\"name\":\"Ali\",\"on\":true}"),
                "two-field body");
        ok(Json.object("name", "Ali", "on", false).equals("{\"name\":\"Ali\",\"on\":false}"),
                "two-field body, false");
    }

    // ---- Bridge parsing --------------------------------------------------

    private static final String ROSTER = """
            {"you": "Hamza", "connected": true, "available": true,
             "friends": [
               {"name": "Ali", "online": true, "version": "1.20.1",
                "status": "playing", "invited": false, "whitelisted": true},
               {"name": "Bea", "online": false, "version": "", "status": ""},
               {"name": "Cai", "online": true, "status": "online", "invited": true}
             ],
             "requests_in": ["Dee"], "requests_out": ["Eli"]}
            """;

    private static void snapshotParsing() {
        section("Bridge: snapshot");
        Bridge.Snapshot s = Bridge.parseSnapshot(ROSTER, "{}");
        ok(s.launcherUp(), "a parsed roster means the launcher is up");
        ok(s.claimed() && s.you().equals("Hamza"), "identity read");
        ok(s.friends().size() == 3, "three friends");
        ok(s.onlineCount() == 2, "two online");
        ok(s.requestsIn().equals(List.of("Dee")), "incoming request");
        ok(s.requestsOut().equals(List.of("Eli")), "outgoing request");
        ok(s.session() == Bridge.Session.NONE, "no session from an empty /status");

        Bridge.Friend ali = s.friends().get(0);
        ok(ali.name().equals("Ali") && ali.whitelisted() && !ali.invited(),
                "per-friend flags read");
        ok(s.friends().stream().anyMatch(Bridge.Friend::invited),
                "invited flag lights up the Join button");

        // Fields the launcher may not send at all (an older launcher, or a
        // future one that drops something) must not blank out the whole screen.
        Bridge.Snapshot old = Bridge.parseSnapshot(
                "{\"friends\": [{\"name\": \"Ali\"}], \"you\": \"Hamza\"}", "");
        ok(old.launcherUp() && old.connected() && old.available(),
                "missing connected/available default to true, not offline");
        ok(old.friends().size() == 1 && !old.friends().get(0).online(),
                "missing online defaults to offline");

        Bridge.Snapshot junk = Bridge.parseSnapshot("<html>500</html>", "<html>");
        ok(junk.friends().isEmpty() && !junk.claimed(),
                "an HTML error page parses to an empty roster, not an exception");

        // A nameless entry is unusable and must be dropped, not rendered blank.
        Bridge.Snapshot blank = Bridge.parseSnapshot(
                "{\"friends\": [{\"online\": true}, {\"name\": \"Ali\"}]}", "{}");
        ok(blank.friends().size() == 1, "nameless roster entries dropped");

        // Value equality is what lets the screen skip rebuilding its widgets.
        ok(Bridge.parseSnapshot(ROSTER, "{}").equals(s),
                "identical bodies produce equal snapshots (no needless rebuilds)");
        ok(!Bridge.parseSnapshot(ROSTER.replace("\"Ali\"", "\"Alj\""), "{}").equals(s),
                "a changed roster produces a different snapshot");
    }

    private static void rosterOrdering() {
        section("Bridge: roster ordering");
        Bridge.Snapshot s = Bridge.parseSnapshot("""
                {"friends": [
                  {"name": "zoe", "online": false},
                  {"name": "Bob", "online": true},
                  {"name": "amy", "online": false},
                  {"name": "Cal", "online": true}
                ]}
                """, "{}");
        ok(s.friends().get(0).name().equals("Bob") && s.friends().get(1).name().equals("Cal"),
                "online friends first");
        ok(s.friends().get(2).name().equals("amy") && s.friends().get(3).name().equals("zoe"),
                "then alphabetical, case-insensitively");
    }

    private static void theOldParsingBugs() {
        section("Bridge: regressions from the regex parser");
        // The old friends() split the whole body on the literal text "}," and
        // then searched each piece for "\"online\": true". Both are defeated by
        // ordinary data. These two cases used to merge rows and light up the
        // wrong one; a real parser is why they can't now.
        Bridge.Snapshot s = Bridge.parseSnapshot("""
                {"friends": [
                  {"name": "Ali", "online": false, "version": "1.20.1 {\\"online\\": true},"},
                  {"name": "Bea", "online": true, "version": ""}
                ]}
                """, "{}");
        ok(s.friends().size() == 2, "a version string containing '},' no longer merges two rows");
        Bridge.Friend ali = s.friends().stream()
                .filter(f -> f.name().equals("Ali")).findFirst().orElseThrow();
        ok(!ali.online(), "a version string containing '\"online\": true' no longer forces online");
        ok(s.friends().stream().filter(Bridge.Friend::online).count() == 1,
                "exactly the friend who is online reads as online");
    }

    private static void sessionParsing() {
        section("Bridge: session");
        ok(Bridge.parseSession("{}") == Bridge.Session.NONE, "no state -> NONE");
        ok(Bridge.parseSession("") == Bridge.Session.NONE, "empty body -> NONE");
        ok(!Bridge.Session.NONE.active(), "NONE is inactive");

        Bridge.Session hosting = Bridge.parseSession(
                "{\"state\": \"hosting_wait_port\", \"peer\": \"Ali\", \"is_host\": true}");
        ok(hosting.active() && hosting.working() && hosting.endable(), "hosting is live work");
        ok(hosting.host(), "host flag read");
        ok(hosting.headline().contains("LAN"), "hosting tells you to open to LAN");
        ok(!hosting.detail().isEmpty(), "hosting explains what happens next");

        Bridge.Session connected = Bridge.parseSession(
                "{\"state\": \"connected\", \"peer\": \"Ali\", \"quality\": \"Direct - 42 ms\","
                        + " \"peer_uid\": \"00000042\","
                        + " \"peer_minecraft_username\": \"Steve\"}");
        ok(!connected.working() && connected.endable(), "connected is idle but leavable");
        ok(connected.headline().contains("Steve")
                && connected.headline().contains("00000042"),
                "connected names the peer by Minecraft username with the Cubeon ID");
        ok(!connected.headline().contains("Ali"), "the relay handle never reaches the headline");
        ok(connected.peerDisplayName().equals("Steve"), "display name is the Minecraft username");
        Bridge.Session connectedOld = Bridge.parseSession(
                "{\"state\": \"connected\", \"peer\": \"Ali\", \"quality\": \"Direct - 42 ms\","
                        + " \"peer_uid\": \"00000042\"}");
        ok(connectedOld.headline().contains("Cubeon ID 00000042"),
                "an older payload without a username shows the Cubeon ID");
        ok(!connectedOld.headline().contains("Ali"),
                "an older payload never shows the internal handle");
        Bridge.Session connectedBlank = Bridge.parseSession(
                "{\"state\": \"connected\", \"peer\": \"Ali\", \"quality\": \"\"}");
        ok(connectedBlank.peerDisplayName().equals("Player"),
                "no metadata at all degrades to a neutral name");
        ok(connected.detail().equals("Direct - 42 ms"), "quality shown verbatim from launcher");

        Bridge.Session failed = Bridge.parseSession(
                "{\"state\": \"failed\", \"peer\": \"Ali\", \"error\": \"NAT is symmetric\","
                        + " \"can_retry\": true}");
        ok(!failed.endable(), "a failed session has nothing left to end");
        ok(failed.canRetry(), "retry offered");
        ok(failed.headline().equals("NAT is symmetric"),
                "the launcher's real error is what the player reads");

        Bridge.Session failedBlank = Bridge.parseSession("{\"state\": \"failed\"}");
        ok(!failedBlank.headline().isEmpty(),
                "a failure with no message still says something");

        // A state this jar has never heard of (a newer launcher) must render as
        // itself instead of as an empty banner.
        Bridge.Session future = Bridge.parseSession("{\"state\": \"teleporting\"}");
        ok(future.active() && future.headline().equals("teleporting"),
                "an unknown state degrades to showing the state name");
        ok(future.endable(), "an unknown live state can still be cancelled");
    }

    private static void eventParsing() {
        section("Bridge: events");
        long[] cursor = {-1};
        List<Bridge.Toast> toasts = Bridge.parseEvents("""
                {"cursor": 7, "events": [
                  {"seq": 6, "text": "Dee sent you a friend request.", "error": false},
                  {"seq": 7, "text": "Ali removed you.", "error": true}
                ]}
                """, cursor);
        ok(cursor[0] == 7, "cursor advanced");
        ok(toasts.size() == 2, "two notifications");
        ok(!toasts.get(0).error() && toasts.get(1).error(), "error flag carried per event");
        ok(toasts.get(1).text().equals("Ali removed you."), "text carried");

        long[] keep = {5};
        ok(Bridge.parseEvents("{\"events\": []}", keep).isEmpty() && keep[0] == 5,
                "a body with no cursor leaves the cursor alone");
        long[] backwards = {5};
        ok(Bridge.parseEvents("{\"cursor\": 3, \"events\": []}", backwards).isEmpty()
                        && backwards[0] == 3,
                "a valid backwards cursor recovers after launcher restart");
        long[] malformed = {5};
        ok(Bridge.parseEvents("{\"cursor\": 1e100, \"events\": []}", malformed).isEmpty()
                        && malformed[0] == 5,
                "an invalid cursor cannot poison notification history");
        long[] missing = {5};
        ok(Bridge.parseEvents("", missing).isEmpty() && missing[0] == 5,
                "an unreachable /events (older launcher) changes nothing");
        long[] any = {0};
        ok(Bridge.parseEvents("{\"cursor\": 3, \"events\": [{\"seq\": 3}]}", any).isEmpty(),
                "a textless event is dropped");
    }

    private static void chatParsing() {
        section("Bridge: chat");
        long[] cursor = {-1};
        List<Bridge.ChatMessage> msgs = Bridge.parseChatMessages("""
                {"friend": "Ali", "you": "Hamza", "messages": [
                  {"seq": 1, "dir": "in", "name": "Ali", "text": "hey", "ts": 1},
                  {"seq": 2, "dir": "out", "name": "Hamza", "text": "hi!", "ts": 1}
                ]}
                """, cursor);
        ok(msgs.size() == 2, "two transcript lines");
        ok(cursor[0] == 2, "cursor advanced to the newest seq");
        ok(msgs.get(0).incoming() && !msgs.get(1).incoming(), "dir maps to incoming");
        ok(msgs.get(0).name().equals("Ali") && msgs.get(1).name().equals("Hamza"),
                "sender names carried");
        ok(msgs.get(1).text().equals("hi!"), "text carried");

        long[] empty = {7};
        ok(Bridge.parseChatMessages("{\"messages\": []}", empty).isEmpty() && empty[0] == 7,
                "an empty page leaves the cursor alone");
        long[] junk = {3};
        ok(Bridge.parseChatMessages("", junk).isEmpty() && junk[0] == 3,
                "an unreachable /chat changes nothing");
        ok(Bridge.parseChatMessages("<html>502</html>", junk).isEmpty(),
                "an HTML error page parses to no lines, not an exception");

        long[] skip = {-1};
        List<Bridge.ChatMessage> one = Bridge.parseChatMessages(
                "{\"messages\": [{\"seq\": 9, \"dir\": \"in\", \"text\": \"no name\"}]}", skip);
        ok(one.size() == 1 && one.get(0).incoming(),
                "a missing dir (older launcher) reads as incoming");
        ok(Bridge.parseChatMessages(
                "{\"messages\": [{\"seq\": 1, \"text\": \"\"}]}", new long[]{-1}).isEmpty(),
                "a textless line is dropped");
        ok(Bridge.parseChatMessages(
                "{\"messages\": [{\"seq\": 1.5, \"text\": \"bad\"}]}",
                new long[]{-1}).isEmpty(),
                "a non-integral chat sequence is dropped");
    }

    private static void playersParsing() {
        section("Bridge: /players parsing");
        List<Bridge.CubeonPlayer> players = Bridge.parsePlayers("""
                {"players": [
                  {"name": "Hamza", "online": true, "skin": "hero.png",
                   "cape": "cube.png", "version": "26.1.2", "status": ""},
                  {"name": "Ali", "online": false, "skin": "", "cape": ""}
                ]}
                """);
        ok(players.size() == 2, "two players carried");
        ok(players.get(0).name().equals("Hamza") && players.get(0).online(),
                "online sorts before offline");
        ok(players.get(0).skin().equals("hero.png")
                && players.get(0).cape().equals("cube.png"),
                "skin and cape names carried");
        ok(players.get(0).presence().equals("Playing 26.1.2"),
                "presence wording matches Friend.presence()");

        ok(Bridge.parsePlayers("{\"players\": []}").isEmpty(),
                "an empty list is an empty list");
        ok(Bridge.parsePlayers("").isEmpty(),
                "an unreachable /players parses to nothing, not an exception");
        ok(Bridge.parsePlayers("<html>404</html>").isEmpty(),
                "an older launcher's 404 page degrades to nothing");
        ok(Bridge.parsePlayers(
                "{\"players\": [{\"online\": true}, {\"name\": \"\"}]}").isEmpty(),
                "nameless entries are dropped");
        ok(Bridge.parsePlayers(
                "{\"players\": [{\"name\": \"Solo\"}]}").size() == 1,
                "every field is optional");
    }

    private static void resultReading() {        section("Bridge: results");
        ok(Bridge.readResult(200, "{\"ok\": true}").ok(), "ok:true");
        Bridge.Result e = Bridge.readResult(200, "{\"ok\": false, \"error\": \"not connected\"}");
        ok(!e.ok() && e.error().equals("not connected"), "error field surfaced");
        // A server-side action (e.g. a claim round trip) reports through "message".
        Bridge.Result m = Bridge.readResult(200,
                "{\"ok\": false, \"message\": \"That name is taken.\"}");
        ok(!m.ok() && m.error().equals("That name is taken."),
                "the message field surfaced, not a generic failure");
        ok(Bridge.readResult(401, "{}").error().contains("Restart"),
                "401 tells the player what to do");
        ok(Bridge.readResult(404, "{}").error().contains("older"),
                "404 means the launcher predates this endpoint");
        Bridge.Result html = Bridge.readResult(500, "<html>oops</html>");
        ok(!html.ok() && html.error().contains("500"),
                "an unparseable failure still names the status code");
        ok(!Bridge.readResult(500, "{\"ok\": true}").ok(),
                "an HTTP error cannot masquerade as success");
        ok(!Bridge.readResult(200, "").ok(), "an empty 200 is not success");
    }

    private static void uidAndPortRules() {
        section("Bridge: UID and port rules");
        ok(Bridge.canonicalUid("42").equals("00000042"), "short IDs are padded to eight digits");
        ok(Bridge.canonicalUid("12345678").equals("12345678"), "eight-digit IDs stay stable");
        ok(Bridge.canonicalUid("123456789012").isEmpty(), "old twelve-digit IDs are rejected");
        ok(Bridge.canonicalUid("100000000").isEmpty(), "IDs above eight digits are rejected");
        ok(Bridge.validPort(1) && Bridge.validPort(65535), "valid port range accepted");
        ok(!Bridge.validPort(0) && !Bridge.validPort(65536), "invalid port range rejected");
        ok(!Bridge.validPort(123.5) && !Bridge.validPort(Double.NaN),
                "fractional and non-finite ports rejected");
    }

    private static void nameChecking() {
        section("Bridge: name rules");
        ok(Bridge.checkName("Hamza") == null, "a normal name passes");
        ok(Bridge.checkName("a_1") == null, "underscores and digits pass");
        ok(Bridge.checkName(null) != null, "null rejected");
        ok(Bridge.checkName("") != null, "empty rejected");
        ok(Bridge.checkName("ab") != null, "two characters rejected");
        ok(Bridge.checkName("a".repeat(17)) != null, "seventeen characters rejected");
        ok(Bridge.checkName("a".repeat(16)) == null, "sixteen characters accepted");
        ok(Bridge.checkName("has space") != null, "space rejected");
        ok(Bridge.checkName("emoji😀") != null, "non-ascii rejected");
        ok(Bridge.checkName("semi;colon") != null, "punctuation rejected");
    }

    private static void presenceText() {
        section("Friend: presence line");
        ok(new Bridge.Friend("A", true, "1.20.1", "playing", false, false).presence()
                .equals("Playing 1.20.1"), "playing a version");
        ok(new Bridge.Friend("A", true, "", "online", false, false).presence()
                .equals("Online"), "online, capitalised");
        ok(new Bridge.Friend("A", true, "", "", false, false).presence()
                .equals("Online"), "online with no status still reads Online");
        ok(new Bridge.Friend("A", false, "", "", false, false).presence()
                .equals("Offline"), "offline");
        // Presence beats the online flag: a friend the server still lists as
        // playing is playing, whatever the flag says.
        ok(new Bridge.Friend("A", false, "1.19.4", "", false, false).presence()
                .equals("Playing 1.19.4"), "a version wins over a stale offline flag");
    }

    private static void connectionText() {
        section("Snapshot: header line");
        ok(Bridge.Snapshot.DOWN.connectionLine().contains("not found"),
                "no launcher");
        ok(Bridge.parseSnapshot("{\"you\": \"\"}", "{}").connectionLine().contains("not set up"),
                "launcher up, nothing claimed");
        // The UID system: the header never advertises the internal claimed
        // name - identity is the Cubeon ID, shown on the Account tab.
        ok(Bridge.parseSnapshot("{\"you\": \"H\", \"you_uid\": \"12345678\", \"connected\": true}", "{}")
                .connectionLine().equals("Connected to Cubeon"), "claimed and connected");
        ok(Bridge.parseSnapshot(
                "{\"you\": \"H\", \"you_uid\": \"12345678\", \"connected\": true}", "{}")
                .youUid().equals("12345678"), "you_uid parsed from /state");
        ok(Bridge.parseSnapshot("{\"you\": \"H\", \"connected\": true}", "{}")
                .youUid().isEmpty(), "older launcher without you_uid degrades to empty");
        ok(Bridge.parseSnapshot(
                "{\"you\": \"H\", \"you_uid\": \"12345678\", \"connected\": false}", "{}")
                .connectionLine().contains("reconnecting"), "claimed but socket down");
        ok(Bridge.parseSnapshot(
                "{\"you\": \"H\", \"you_uid\": \"12345678\", \"available\": false}", "{}")
                .connectionLine().contains("add-on"), "launcher lacks websocket-client");
    }

    // ---- harness ---------------------------------------------------------

    private static void section(String title) {
        System.out.println();
        System.out.println(title);
    }

    private static void ok(boolean condition, String label) {
        if (condition) {
            passed++;
            System.out.println("  ok  " + label);
        } else {
            failed++;
            System.out.println("FAIL  " + label);
        }
    }
}
