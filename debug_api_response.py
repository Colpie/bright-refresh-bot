"""Quick debug script to see what API returns for vacancy descriptions."""
import asyncio
from dotenv import load_dotenv
from src.config import load_config
from src.api.client import BrightStaffingClient

async def main():
    load_dotenv()
    config = load_config()

    async with BrightStaffingClient(config.api) as client:
        # Get vacancy #13293 (the old closed one with good formatting)
        response = await client.get_vacancies_by_office(
            office_id="1",
            extra_data=True,
        )

        if response.success and response.data:
            vacancies = response.data.get("vacancies", [])
            print(f"Total vacancies found: {len(vacancies)}")

            # Find any vacancy from the recent run - just grab the first one
            if vacancies:
                v = vacancies[0]
                print("=" * 80)
                print(f"Vacancy {v.get('uid')}: {v.get('function')}")
                print(f"Status: {v.get('status')}")
                print("=" * 80)

                desc_function = v.get("desc_function", "")
                print("\n### RAW desc_function (first 800 chars) ###")
                print(repr(desc_function[:800]))  # Show with escape sequences
                print("\n### RENDERED desc_function ###")
                print(desc_function[:800])
                print("\n### assigned_user_mail ###")
                print(repr(v.get("assigned_user_mail")))
                print("\n### assigned_user_id ###")
                print(repr(v.get("assigned_user_id")))

                print("\n### ALL DESC FIELDS ###")
                for key in sorted(v.keys()):
                    if 'desc' in key.lower():
                        val = v.get(key, '')
                        print(f"{key}: {len(val) if val else 0} chars")

                print("\n" + "=" * 80 + "\n")
            else:
                print("No vacancies found!")

if __name__ == "__main__":
    asyncio.run(main())
