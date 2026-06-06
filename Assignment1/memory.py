import json
import asyncio


async def load_user_data(filename):
    await asyncio.sleep(0)

    with open(filename, "r") as f:
        data = json.load(f)

    return data


async def main():
    user = await load_user_data("user_data.json")

    print("\n===== USER MEMORY =====")
    print(f"Name    : {user['name']}")
    print(f"Email   : {user['email']}")
    print(f"Phone   : {user['phone']}")
    print(f"Address : {user['address']}")
    print("=======================\n")


if __name__ == "__main__":
    asyncio.run(main()) 