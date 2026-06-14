import json


def pretty_print(result: dict):
    print(json.dumps(result, indent=4))