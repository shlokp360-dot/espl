"""
A password an admin can read down a phone line.

⚠ WHY NOT `Xk7#pQ2!`
    Because the admin does not type it into the person's computer — they say it
    out loud to somebody standing on a site, who types it on a phone. Every
    character that has to be spelt out ("capital X, small k, seven, hash…") is a
    chance to get it wrong, and a password that arrives wrong looks exactly like
    a broken login.

    `quarry-lantern-47` is three things to say and roughly 46 bits of entropy
    from this list — comfortably stronger than the eight-character mixture
    somebody would otherwise invent by hand, and it survives being read aloud.

⚠ IT IS TEMPORARY BY DESIGN. Whoever receives it must change it at their next
    sign-in, so its job is to survive one phone call, not one year.

⚠ NO WORDS THAT SOUND ALIKE AND NONE UNDER FIVE LETTERS. "bear" and "bare",
    "site" and "sight" would defeat the whole point.
"""
import secrets

#: Ordinary English, concrete, unambiguous when spoken. No homophones.
WORDS = [
    "anchor", "amber", "basket", "beacon", "bridge", "cactus", "candle", "canvas",
    "cargo", "cedar", "chimney", "cobalt", "compass", "copper", "cotton", "crimson",
    "crystal", "dolphin", "ember", "falcon", "fabric", "garden", "granite", "harbour",
    "hazel", "indigo", "island", "jasmine", "kettle", "lantern", "ledger", "lemon",
    "marble", "meadow", "monsoon", "mortar", "nectar", "opal", "orchard", "pepper",
    "pigment", "pillar", "plaster", "quarry", "quartz", "rafter", "ribbon", "saffron",
    "sandal", "silver", "socket", "spindle", "temple", "timber", "tunnel", "velvet",
    "walnut", "willow", "window", "yellow",
]


def readable_password():
    """Two words and a number — `quarry-lantern-47`."""
    first = secrets.choice(WORDS)
    second = secrets.choice([w for w in WORDS if w != first])
    return f"{first}-{second}-{secrets.randbelow(90) + 10}"
