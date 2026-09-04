"""
Discord-style ':shortcode:' emoji support for chat messages.

Kept as its own small module (not stuffed into friends.py) since it's pure
text transformation with no networking/state, and both the message composer
and the emoji-picker popup need the same shortcode table.
"""
import re

# A practical common subset (not the full Discord/Unicode set - that's
# thousands of entries) covering the emoji people actually reach for in
# chat. Easy to extend: just add "name": "🙂" pairs.
SHORTCODES: dict[str, str] = {
    "smile": "😄", "grin": "😁", "joy": "😂", "rofl": "🤣", "wink": "😉",
    "blush": "😊", "slight_smile": "🙂", "upside_down": "🙃", "relieved": "😌",
    "heart_eyes": "😍", "kiss": "😘", "yum": "😋", "sunglasses": "😎",
    "thinking": "🤔", "neutral": "😐", "expressionless": "😑", "no_mouth": "😶",
    "smirk": "😏", "unamused": "😒", "roll_eyes": "🙄", "grimace": "😬",
    "lying": "🤥", "relaxed": "☺️", "yawn": "🥱", "sleepy": "😪", "sleeping": "😴",
    "mask": "😷", "sick": "🤒", "hurt": "🤕", "vomit": "🤮", "sneeze": "🤧",
    "hot": "🥵", "cold": "🥶", "dizzy": "😵", "exploding_head": "🤯",
    "cowboy": "🤠", "party": "🥳", "shush": "🤫", "zip": "🤐",
    "worried": "😟", "frowning": "☹️", "slight_frown": "🙁", "open_mouth": "😮",
    "hushed": "😯", "astonished": "😲", "flushed": "😳", "pleading": "🥺",
    "cry": "😢", "sob": "😭", "scream": "😱", "confounded": "😖",
    "persevere": "😣", "disappointed": "😞", "sweat": "😓", "weary": "😩",
    "tired": "😫", "angry": "😠", "rage": "😡", "triumph": "😤",
    "innocent": "😇", "cursing": "🤬", "poop": "💩", "clown": "🤡",
    "ghost": "👻", "skull": "💀", "alien": "👽", "robot": "🤖",
    "heart": "❤️", "orange_heart": "🧡", "yellow_heart": "💛",
    "green_heart": "💚", "blue_heart": "💙", "purple_heart": "💜",
    "black_heart": "🖤", "white_heart": "🤍", "broken_heart": "💔",
    "sparkling_heart": "💖", "two_hearts": "💕", "heartbeat": "💓",
    "fire": "🔥", "100": "💯", "star": "⭐", "sparkles": "✨",
    "boom": "💥", "zap": "⚡", "sweat_drops": "💦", "dash": "💨",
    "thumbsup": "👍", "+1": "👍", "thumbsdown": "👎", "-1": "👎",
    "ok_hand": "👌", "wave": "👋", "clap": "👏", "pray": "🙏",
    "muscle": "💪", "point_up": "☝️", "point_down": "👇",
    "point_left": "👈", "point_right": "👉", "eyes": "👀",
    "raised_hands": "🙌", "handshake": "🤝", "fist": "✊", "punch": "👊",
    "middle_finger": "🖕", "call_me": "🤙", "crossed_fingers": "🤞",
    "check": "✅", "x": "❌", "warning": "⚠️", "question": "❓",
    "exclamation": "❗", "no_entry": "⛔", "100_points": "💯",
    "tada": "🎉", "confetti": "🎊", "gift": "🎁", "trophy": "🏆",
    "medal": "🏅", "crown": "👑", "gem": "💎", "moneybag": "💰",
    "rocket": "🚀", "gear": "⚙️", "hammer": "🔨", "wrench": "🔧",
    "pick": "⛏️", "shield": "🛡️", "sword": "🗡️", "bomb": "💣",
    "gun": "🔫", "video_game": "🎮", "joystick": "🕹️", "dice": "🎲",
    "chess": "♟️", "art": "🎨", "musical_note": "🎵", "notes": "🎶",
    "headphones": "🎧", "microphone": "🎤", "camera": "📷", "movie_camera": "🎥",
    "tv": "📺", "computer": "💻", "keyboard": "⌨️", "mouse": "🖱️",
    "battery": "🔋", "plug": "🔌", "bulb": "💡", "flashlight": "🔦",
    "lock": "🔒", "unlock": "🔓", "key": "🔑", "hourglass": "⏳",
    "clock": "🕐", "alarm_clock": "⏰", "calendar": "📅", "pushpin": "📌",
    "paperclip": "📎", "pencil": "✏️", "memo": "📝", "book": "📖",
    "books": "📚", "mailbox": "📬", "email": "📧", "inbox": "📥",
    "outbox": "📤", "package": "📦", "chart": "📊", "chart_up": "📈",
    "chart_down": "📉", "coffee": "☕", "beer": "🍺", "beers": "🍻",
    "pizza": "🍕", "burger": "🍔", "fries": "🍟", "cake": "🍰",
    "cookie": "🍪", "candy": "🍬", "apple": "🍎", "watermelon": "🍉",
    "sun": "☀️", "cloud": "☁️", "rain": "🌧️", "snow": "❄️",
    "rainbow": "🌈", "moon": "🌙", "earth": "🌍", "star2": "🌟",
    "dog": "🐶", "cat": "🐱", "creeper": "🟩", "cow": "🐮", "pig": "🐷",
    "chicken": "🐔", "frog": "🐸", "bee": "🐝", "spider": "🕷️",
    "snake": "🐍", "dragon": "🐉", "unicorn": "🦄", "wolf": "🐺",
    "car": "🚗", "airplane": "✈️", "train": "🚆", "bike": "🚲",
    "house": "🏠", "office": "🏢", "castle": "🏰", "tent": "⛺",
    "flag": "🚩", "checkered_flag": "🏁", "no": "🚫", "recycle": "♻️",
}

_PATTERN = re.compile(r":([a-zA-Z0-9_+\-]+):")


def expand_emoji(text: str) -> str:
    """Replaces every ':shortcode:' in text with its emoji, leaving unknown
    codes untouched (so ':notarealcode:' stays literal text rather than
    disappearing, which would be confusing)."""
    if not text or ":" not in text:
        return text

    def _sub(match: re.Match) -> str:
        code = match.group(1).lower()
        return SHORTCODES.get(code, match.group(0))

    return _PATTERN.sub(_sub, text)


def all_shortcodes() -> list[tuple[str, str]]:
    """Sorted (shortcode, emoji) pairs for the picker UI."""
    return sorted(SHORTCODES.items())
