from app.intent_parser import parse_intent
from app.utils import pretty_print


while True:
    command = input("\nEnter command: ")

    if command.lower() == "exit":
        break

    result = parse_intent(command)
    pretty_print(result)