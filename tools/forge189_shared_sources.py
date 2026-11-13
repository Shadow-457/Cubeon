"""Lower the deliberately shared client classes to Java 8 for the legacy port.

The generated files are build inputs, not a second hand-maintained geometry or
protocol implementation. javac --release 8 verifies the complete result.
"""
from pathlib import Path
import re

FILES = (
    "Json.java", "Bridge.java", "hud/Freelook.java", "hud/HudFeatures.java",
    "cosmetics/CosmeticCatalog.java", "cosmetics/CosmeticGeometry.java",
    "cosmetics/CosmeticAnimation.java", "cosmetics/WingAction.java",
    "emotes/EmotePose.java", "emotes/EmoteState.java", "emotes/EmoteFavorites.java",
    "emotes/EmoteRoom.java", "cosmetics/CosmeticSelection.java", "cosmetics/RemoteCosmetics.java",
    "hud/CubeonHudConfig.java",
    "ui/ClientTheme.java",
    "hud/CameraBlur.java", "hud/HealthHearts.java",
)


def close_brace(text, start):
    depth, quote, comment, escaped = 0, None, None, False
    i = start
    while i < len(text):
        c, pair = text[i], text[i:i + 2]
        if comment == "line":
            if c == "\n":
                comment = None
        elif comment == "block":
            if pair == "*/":
                comment = None
                i += 1
        elif quote:
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == quote:
                quote = None
        elif pair in ("//", "/*"):
            comment = "line" if pair == "//" else "block"
            i += 1
        elif c in ("'", '"'):
            quote = c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ValueError("Unclosed Java block")


def record_classes(text):
    pattern = re.compile(r"\b(public|private)\s+record\s+(\w+)\s*\((.*?)\)\s*\{", re.S)
    while match := pattern.search(text):
        end = close_brace(text, match.end() - 1)
        components = re.split(r",(?![^<]*>)", match[3])
        parts = [tuple(c.strip().rsplit(None, 1)) for c in components if c.strip()]
        name = match[2]
        fields = "\n".join(f"private final {t} {n};" for t, n in parts)
        arguments = ", ".join(f"{t} {n}" for t, n in parts)
        assignments = " ".join(f"this.{n} = {n};" for _, n in parts)
        accessors = "\n".join(f"public {t} {n}() {{ return {n}; }}" for t, n in parts)
        equals = " && ".join(f"java.util.Objects.deepEquals({n}, other.{n})" for _, n in parts) or "true"
        values = ", ".join(n for _, n in parts)
        extra = f"""
public boolean equals(Object obj) {{
    if (obj == this) return true;
    if (!(obj instanceof {name})) return false;
    {name} other = ({name}) obj;
    return {equals};
}}
public int hashCode() {{ return java.util.Arrays.deepHashCode(new Object[]{{{values}}}); }}
"""
        body = text[match.end():end]
        replacement = f"{match[1]} static final class {name} {{\n{fields}\npublic {name}({arguments}) {{ {assignments} }}\n{accessors}\n{extra}\n{body}\n}}"
        text = text[:match.start()] + replacement + text[end + 1:]
    return text


def switches(text):
    branch = re.compile(r"(?:case\s+(?:\"[^\"]*\"|'(?:\\.|[^'])+'|[\w]+)(?:\s*,\s*\w+)*|default)\s*->")
    scan = 0
    while match := re.compile(r"switch\s*\(([^()]*)\)\s*\{").search(text, scan):
        end = close_brace(text, match.end() - 1)
        body = text[match.end():end]
        labels = list(branch.finditer(body))
        if not labels:
            scan = end + 1
            continue
        prefix = text[:match.start()]
        expression = re.search(r"return\s*$", prefix)
        assignment = re.search(r"([\w.<>]+)\s+(\w+)\s*=\s*$", prefix) if not expression else None
        output = []
        for i, label in enumerate(labels):
            head = label[0][:-2].strip()
            if head.startswith("case"):
                values = head[4:].strip().split(",")
                head = " ".join("case " + v.strip() + ":" for v in values)
            else:
                head = "default:"
            value = body[label.end():labels[i + 1].start() if i + 1 < len(labels) else len(body)].strip()
            if expression or assignment:
                value = value.rstrip("; \t\r\n")
                if value.startswith("{"):
                    stop = close_brace(value, 0)
                    inside = value[1:stop]
                    inside = re.sub(r"yield ([^;]+);", r"return \1;" if expression else assignment[2] + r" = \1; break;", inside)
                    statement = "{" + inside + "}"
                else:
                    statement = f"return {value};" if expression else f"{assignment[2]} = {value}; break;"
            elif value.startswith("{"):
                stop = close_brace(value, 0)
                statement = "{" + value[1:stop] + "\nbreak;\n}" + value[stop + 1:]
            else:
                statement = value + ("" if value.startswith(("throw ", "return ")) else " break;")
            output.append(head + " " + statement)
        start = expression.start() if expression else assignment.start() if assignment else match.start()
        prelude = f"{assignment[1]} {assignment[2]}; " if assignment else ""
        replacement = prelude + "switch (" + match[1] + ") {\n" + "\n".join(output) + "\n}"
        stop = end + 1
        if (expression or assignment) and text[stop:stop + 1] == ";":
            stop += 1
        text = text[:start] + replacement + text[stop:]
        scan = start + len(replacement)
    return text


def patterns(text):
    types = r"(?:Map<\?,\s*\?>|List<\?>|String|Number|Boolean|Double)"
    condition = re.compile(r"if\s*\(\s*(\w+)\s+instanceof\s+(" + types + r")\s+(\w+)([^\n]*?)\)\s*\{")
    def lower(match):
        value, kind, name, rest = match.groups()
        rest = re.sub(r"\b" + name + r"\b", f"(({kind}) {value})", rest)
        return f"if ({value} instanceof {kind}{rest}) {{ {kind} {name} = ({kind}) {value};"
    text = condition.sub(lower, text)
    ternary = re.compile(r"(\w+)\s+instanceof\s+(" + types + r")\s+(\w+)\s*\?([^;\n]+)")
    def lower_ternary(match):
        value, kind, name, rest = match.groups()
        rest = re.sub(r"\b" + name + r"\b", f"(({kind}) {value})", rest)
        return f"{value} instanceof {kind} ?{rest}"
    return ternary.sub(lower_ternary, text)


def generate(root, destination):
    source = root / "mod/src/main/java/com/cubeon/client"
    for relative in FILES:
        text = (source / relative).read_text()
        if relative == "hud/CubeonHudConfig.java":
            text = text.replace('import net.fabricmc.loader.api.FabricLoader;', '')
            text = text.replace('FabricLoader.getInstance().getConfigDir()',
                                'net.minecraft.client.Minecraft.getMinecraft().mcDataDir.toPath().resolve("config")')
            text = text.replace('Files.readString(source, StandardCharsets.UTF_8)',
                                'new String(com.cubeon.compat.Collections8.read(source, 65536), StandardCharsets.UTF_8)')
            text = text.replace('Files.writeString(FILE, GSON.toJson(instance) + System.lineSeparator(), StandardCharsets.UTF_8);',
                                'com.cubeon.compat.Collections8.writeAtomic(FILE, (GSON.toJson(instance) + System.lineSeparator()).getBytes(StandardCharsets.UTF_8));')
            text = text.replace('CubeonHudClient.LOGGER', 'org.apache.logging.log4j.LogManager.getLogger("CubeonClient")')
        text = record_classes(text)
        text = switches(text)
        text = patterns(text)
        text = text.replace("java.net.http.HttpTimeoutException", "java.net.SocketTimeoutException")
        text = text.replace("java.net.http.", "com.cubeon.compat.")
        text = text.replace("Path.of(", "java.nio.file.Paths.get(")
        text = text.replace("Files.readString(TOKEN_FILE, StandardCharsets.UTF_8)",
                            "new String(Files.readAllBytes(TOKEN_FILE), StandardCharsets.UTF_8)")
        text = text.replace("List.of(", "com.cubeon.compat.Collections8.list(")
        text = text.replace("List.copyOf(", "com.cubeon.compat.Collections8.copy(")
        text = text.replace("Map.of()", "java.util.Collections.emptyMap()")
        text = text.replace('Map.of("ok", false, "error", ', 'com.cubeon.compat.Collections8.map("ok", false, "error", ')
        text = text.replace('URLEncoder.encode(java.nio.file.Paths.get("").toAbsolutePath().normalize().toString(), StandardCharsets.UTF_8)', 'com.cubeon.compat.Collections8.encode(java.nio.file.Paths.get("").toAbsolutePath().normalize().toString())')
        text = text.replace('java.net.URLEncoder.encode(kind, StandardCharsets.UTF_8)', 'com.cubeon.compat.Collections8.encode(kind)')
        text = text.replace('var request = HttpRequest.', 'HttpRequest request = HttpRequest.')
        text = text.replace('var response = http.send(', 'HttpResponse<String> response = http.send(')
        text = re.sub(r"(\w+)\.isBlank\(\)", r"com.cubeon.compat.Collections8.blank(\1)", text)
        text = text.replace("valid.toArray(String[]::new)", "valid.toArray(new String[0])")
        text = text.replace('"0".repeat(8 - text.length())', '"00000000".substring(text.length())')
        text = text.replace('URLEncoder.encode(before.peer(), StandardCharsets.UTF_8)',
                            'com.cubeon.compat.Collections8.encode(before.peer())')
        text = text.replace('var merged =', 'java.util.TreeMap<Long, ChatMessage> merged =')
        text = text.replace('var weight =', 'CosmeticGeometry.FeatherWeight weight =')
        text = text.replace('var f =', 'CosmeticCatalog.Feather f =')
        text = text.replace('for (var box :', 'for (CosmeticCatalog.Box box :')
        text = text.replace('try (var stream =', 'try (java.io.InputStream stream =')
        text = re.sub(r'stream.readNBytes\((\d[\d_]*)\)', r'com.cubeon.compat.Collections8.read(stream, \1)', text)
        text = text.replace('var iterator =', 'java.util.Iterator<java.util.Map.Entry<String, Entry>> iterator =')
        text = text.replace('import java.util.HexFormat;', '')
        text = text.replace('HexFormat.of().formatHex(', 'com.cubeon.compat.Collections8.hex(')
        text = text.replace('private Result post(', 'public Result post(')
        target = destination / "com/cubeon/client" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
