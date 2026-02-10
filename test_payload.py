"""Test to see actual payload being sent to addVacancy."""
import asyncio
import json
from dotenv import load_dotenv
from src.config import load_config
from src.api.client import BrightStaffingClient
from src.api.vacancy import VacancyService

async def main():
    load_dotenv()
    config = load_config()

    async with BrightStaffingClient(config.api) as client:
        vacancy_service = VacancyService(client)

        # Get first open vacancy
        vacancies = await vacancy_service.get_all_open_vacancies("1")
        if not vacancies:
            print("No vacancies found!")
            return

        vacancy = vacancies[0]
        print(f"Testing with vacancy: {vacancy.id} - {vacancy.title}")

        # Fetch complete details
        complete = await vacancy_service.get_complete_vacancy(vacancy)

        # Build the duplication payload
        payload = complete.build_duplication_payload(channels=[1, 2])

        # Add consultant
        await vacancy_service._ensure_user_map()
        user_id = vacancy_service._resolve_assigned_user_id(complete.vacancy)
        if user_id:
            payload["assigned_user_id"] = user_id
            print(f"\nConsultant: email={complete.vacancy.raw_data.get('assigned_user_mail')}, user_id={user_id}")

        # Print all field names
        print(f"\n=== PAYLOAD FIELDS ({len(payload)} total) ===")
        for key in sorted(payload.keys()):
            val = payload[key]
            if isinstance(val, str) and len(val) > 100:
                print(f"  {key}: <string, {len(val)} chars>")
            else:
                print(f"  {key}: {type(val).__name__} = {repr(val)[:80]}")

        # Check for assigned_user fields
        print("\n=== ASSIGNED USER FIELDS ===")
        for key in sorted(payload.keys()):
            if 'assigned' in key.lower() or 'user' in key.lower() or 'consultant' in key.lower():
                print(f"  {key} = {repr(payload[key])}")

if __name__ == "__main__":
    asyncio.run(main())
