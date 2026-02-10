"""Check user lookup."""
import asyncio
from dotenv import load_dotenv
from src.config import load_config
from src.api.client import BrightStaffingClient

async def main():
    load_dotenv()
    config = load_config()

    async with BrightStaffingClient(config.api) as client:
        response = await client.get_users()

        if response.success and response.data:
            users = response.data.get("users", [])
            print(f"Total users: {len(users)}\n")

            # Find Dario
            for u in users:
                mail = u.get("mail", "").strip()
                if "dario" in mail.lower():
                    print(f"User: {u.get('full_name')}")
                    print(f"Email: {mail}")
                    print(f"UID: {u.get('uid')}")
                    print()

if __name__ == "__main__":
    asyncio.run(main())
