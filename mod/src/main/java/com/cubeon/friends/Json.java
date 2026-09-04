package com.cubeon.friends;

import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * A tiny, dependency-free JSON reader/writer.
 *
 * Minecraft bundles Gson, but relying on it couples this mod to whatever Gson
 * version a given Minecraft release happens to ship - the exact kind of
 * incidental version coupling that stops one jar from working on more than one
 * Minecraft version. 200 lines of parser is a cheaper price than that.
 *
 * <p>Deliberately contains NO Minecraft imports, so it compiles and unit-tests
 * with a plain JDK (see mod/tools/SelfTest.java).
 *
 * <p>Replaces the regex/substring scraping this mod used to do. That approach
 * was wrong in ways that showed up as UI bugs rather than errors: the friends
 * list was split on the literal text {@code "},"}, so a friend whose presence
 * string contained that sequence merged two rows into one, and presence was
 * read by searching the whole response for {@code "\"online\": true"}, which
 * matched a *different* friend's field and lit up the wrong row.
 */
public final class Json {

    /** Refuse absurd input rather than trusting a local socket blindly. */
    private static final int MAX_DEPTH = 32;

    private final String src;
    private int pos;
    private int depth;

    private Json(String src) {
        this.src = src;
    }

    /** Thrown for malformed input. Callers normally use the lenient helpers below. */
    public static final class JsonException extends Exception {
        private static final long serialVersionUID = 1L;

        JsonException(String message) {
            super(message);
        }
    }

    // ---- parsing ---------------------------------------------------------

    /**
     * Parses any JSON value. Objects become {@code Map<String,Object>}, arrays
     * {@code List<Object>}, numbers {@code Double}, and null a Java null.
     */
    public static Object parse(String text) throws JsonException {
        if (text == null) {
            throw new JsonException("no input");
        }
        Json p = new Json(text);
        p.skipWhitespace();
        Object value = p.readValue();
        p.skipWhitespace();
        if (p.pos < p.src.length()) {
            throw new JsonException("trailing content at " + p.pos);
        }
        return value;
    }

    /**
     * Lenient object parse: an empty map for anything that isn't a JSON object,
     * so a garbled or error response degrades to "no data" instead of throwing
     * on the caller's thread.
     */
    public static Map<String, Object> parseObject(String text) {
        try {
            Object value = parse(text);
            if (value instanceof Map<?, ?> map) {
                @SuppressWarnings("unchecked")
                Map<String, Object> typed = (Map<String, Object>) map;
                return typed;
            }
        } catch (JsonException ignored) {
            // fall through - callers treat an empty map as "nothing usable"
        }
        return Map.of();
    }

    private Object readValue() throws JsonException {
        if (pos >= src.length()) {
            throw new JsonException("unexpected end of input");
        }
        char c = src.charAt(pos);
        switch (c) {
            case '{':
                return readObject();
            case '[':
                return readArray();
            case '"':
                return readString();
            case 't':
                expect("true");
                return Boolean.TRUE;
            case 'f':
                expect("false");
                return Boolean.FALSE;
            case 'n':
                expect("null");
                return null;
            default:
                return readNumber();
        }
    }

    private Map<String, Object> readObject() throws JsonException {
        enter();
        pos++; // '{'
        Map<String, Object> out = new LinkedHashMap<>();
        skipWhitespace();
        if (peek() == '}') {
            pos++;
            depth--;
            return out;
        }
        while (true) {
            skipWhitespace();
            if (peek() != '"') {
                throw new JsonException("expected a key at " + pos);
            }
            String key = readString();
            skipWhitespace();
            if (peek() != ':') {
                throw new JsonException("expected ':' at " + pos);
            }
            pos++;
            skipWhitespace();
            out.put(key, readValue());
            skipWhitespace();
            char c = peek();
            pos++;
            if (c == '}') {
                depth--;
                return out;
            }
            if (c != ',') {
                throw new JsonException("expected ',' or '}' at " + (pos - 1));
            }
        }
    }

    private List<Object> readArray() throws JsonException {
        enter();
        pos++; // '['
        List<Object> out = new ArrayList<>();
        skipWhitespace();
        if (peek() == ']') {
            pos++;
            depth--;
            return out;
        }
        while (true) {
            skipWhitespace();
            out.add(readValue());
            skipWhitespace();
            char c = peek();
            pos++;
            if (c == ']') {
                depth--;
                return out;
            }
            if (c != ',') {
                throw new JsonException("expected ',' or ']' at " + (pos - 1));
            }
        }
    }

    private String readString() throws JsonException {
        pos++; // opening quote
        StringBuilder sb = new StringBuilder();
        while (true) {
            if (pos >= src.length()) {
                throw new JsonException("unterminated string");
            }
            char c = src.charAt(pos++);
            if (c == '"') {
                return sb.toString();
            }
            if (c != '\\') {
                sb.append(c);
                continue;
            }
            if (pos >= src.length()) {
                throw new JsonException("unterminated escape");
            }
            char esc = src.charAt(pos++);
            switch (esc) {
                case '"' -> sb.append('"');
                case '\\' -> sb.append('\\');
                case '/' -> sb.append('/');
                case 'b' -> sb.append('\b');
                case 'f' -> sb.append('\f');
                case 'n' -> sb.append('\n');
                case 'r' -> sb.append('\r');
                case 't' -> sb.append('\t');
                case 'u' -> {
                    if (pos + 4 > src.length()) {
                        throw new JsonException("truncated \\u escape");
                    }
                    try {
                        sb.append((char) Integer.parseInt(src.substring(pos, pos + 4), 16));
                    } catch (NumberFormatException ex) {
                        throw new JsonException("bad \\u escape at " + pos);
                    }
                    pos += 4;
                }
                default -> throw new JsonException("bad escape \\" + esc);
            }
        }
    }

    private Double readNumber() throws JsonException {
        int start = pos;
        if (peek() == '-' || peek() == '+') {
            pos++;
        }
        while (pos < src.length()) {
            char c = src.charAt(pos);
            if ((c >= '0' && c <= '9') || c == '.' || c == 'e' || c == 'E'
                    || c == '-' || c == '+') {
                pos++;
            } else {
                break;
            }
        }
        if (start == pos) {
            throw new JsonException("expected a value at " + start);
        }
        try {
            return Double.valueOf(src.substring(start, pos));
        } catch (NumberFormatException ex) {
            throw new JsonException("bad number at " + start);
        }
    }

    private void enter() throws JsonException {
        if (++depth > MAX_DEPTH) {
            throw new JsonException("nested too deeply");
        }
    }

    private char peek() throws JsonException {
        if (pos >= src.length()) {
            throw new JsonException("unexpected end of input");
        }
        return src.charAt(pos);
    }

    private void expect(String literal) throws JsonException {
        if (!src.startsWith(literal, pos)) {
            throw new JsonException("expected " + literal + " at " + pos);
        }
        pos += literal.length();
    }

    private void skipWhitespace() {
        while (pos < src.length()) {
            char c = src.charAt(pos);
            if (c == ' ' || c == '\t' || c == '\n' || c == '\r') {
                pos++;
            } else {
                break;
            }
        }
    }

    // ---- typed access ----------------------------------------------------
    // Every getter is total: a missing key, a wrong type, or a null all yield
    // the supplied default. Screen code therefore never needs a try/catch.

    public static String str(Object holder, String key, String fallback) {
        Object v = member(holder, key);
        return v instanceof String s ? s : fallback;
    }

    public static boolean bool(Object holder, String key, boolean fallback) {
        Object v = member(holder, key);
        if (v instanceof Boolean b) {
            return b;
        }
        return fallback;
    }

    /** {@code Double.NaN} when absent, which callers test with {@link Double#isNaN}. */
    public static double num(Object holder, String key) {
        Object v = member(holder, key);
        return v instanceof Double d ? d : Double.NaN;
    }

    public static List<Object> list(Object holder, String key) {
        Object v = member(holder, key);
        return v instanceof List<?> l ? Collections.unmodifiableList(new ArrayList<>(l))
                                      : List.of();
    }

    /** Every element of {@code key}'s array that is a string, in order. */
    public static List<String> strings(Object holder, String key) {
        List<String> out = new ArrayList<>();
        for (Object item : list(holder, key)) {
            if (item instanceof String s && !s.isEmpty()) {
                out.add(s);
            }
        }
        return out;
    }

    private static Object member(Object holder, String key) {
        return holder instanceof Map<?, ?> map ? map.get(key) : null;
    }

    // ---- writing ---------------------------------------------------------

    /**
     * A JSON string literal, quotes included.
     *
     * <p>This is the mod's only outbound-encoding path, and it used to be
     * {@code name.replace("\"", "")}. Stripping quotes is not escaping: a name
     * ending in a backslash escaped the closing quote and produced a body the
     * launcher rejected as malformed, and a control character did the same.
     */
    public static String quote(String value) {
        StringBuilder sb = new StringBuilder(value == null ? 2 : value.length() + 2);
        sb.append('"');
        if (value != null) {
            for (int i = 0; i < value.length(); i++) {
                char c = value.charAt(i);
                switch (c) {
                    case '"' -> sb.append("\\\"");
                    case '\\' -> sb.append("\\\\");
                    case '\n' -> sb.append("\\n");
                    case '\r' -> sb.append("\\r");
                    case '\t' -> sb.append("\\t");
                    case '\b' -> sb.append("\\b");
                    case '\f' -> sb.append("\\f");
                    default -> {
                        if (c < 0x20 || c == 0x7f) {
                            sb.append(String.format("\\u%04x", (int) c));
                        } else {
                            sb.append(c);
                        }
                    }
                }
            }
        }
        sb.append('"');
        return sb.toString();
    }

    /** {@code {"name": "<value>"}} - the shape every POST in this mod sends. */
    public static String object(String key, String value) {
        return "{" + quote(key) + ":" + quote(value) + "}";
    }

    /** {@code {"name": "<value>", "<flag>": true|false}}. */
    public static String object(String key, String value, String flag, boolean on) {
        return "{" + quote(key) + ":" + quote(value) + ","
                + quote(flag) + ":" + (on ? "true" : "false") + "}";
    }

    /** {@code {"<key1>": "<value1>", "<key2>": "<value2>"}}. */
    public static String object(String key1, String value1, String key2, String value2) {
        return "{" + quote(key1) + ":" + quote(value1) + ","
                + quote(key2) + ":" + quote(value2) + "}";
    }
}
