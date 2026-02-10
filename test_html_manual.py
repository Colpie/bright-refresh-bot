"""Test HTML reconstruction with real API data."""
from src.utils.html_reconstruct import reconstruct_html

# Real text from API (from the debug output above)
test_text = """


Ben jij klaar voor werk dat blijft plakken? Letterlijk én figuurlijk.
Heb jij ervaring met TIG- of autogeen lassen?&nbsp;
Werk je graag aan installaties die écht van belang zijn  van ziekenhuizen tot kantoorgebouwen?&nbsp;
Dan hebben wij een vaste plek voor jou

Wat ga je doen?
Als lasser binnen de HVAC-projecten werk je mee aan het lassen en samenstellen van buisleidingen voor verwarming, koeling, ventilatie en sanitair.&nbsp;
Je werkt op verplaatsing, in team, en soms ook zelfstandig.

Een greep uit je taken:
Je last HVAC-leidingen (meestal staal) volgens plan.Je werkt met TIG- of autogeen lastechnieken.Je monteert en assembleert stukken op maat.Je werkt nauw samen met monteurs en projectleiders.Je volgt de veiligheidsregels strikt op.Je werkt voornamelijk op grotere werven in Oost-Vlaanderen."""

print("=" * 80)
print("ORIGINAL TEXT")
print("=" * 80)
print(test_text)
print("\n" + "=" * 80)
print("RECONSTRUCTED HTML")
print("=" * 80)
result = reconstruct_html(test_text)
print(result)
print("\n" + "=" * 80)
print("CHECK FOR BULLETS")
print("=" * 80)
if "<ul>" in result and "<li>" in result:
    print("✓ Bullets detected and converted to HTML!")
else:
    print("✗ No bullets in output")

if "<strong>" in result:
    print("✓ Headers detected!")
else:
    print("✗ No headers detected")
