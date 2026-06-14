from app.intent_parser import parse_intent
from app.utils import pretty_print

commands = [
    "apply to this job",
    "close all tabs",
    "email this summary to my boss",
    "open linkedin",
    "fill the signup form",
    "summarize this webpage",
    "click the apply button",
    "navigate to github",
    "login to gmail",
    "book a flight to Delhi"
]

for cmd in commands:
    print("=" * 50)
    print("COMMAND:", cmd)

    result = parse_intent(cmd)
    pretty_print(result)