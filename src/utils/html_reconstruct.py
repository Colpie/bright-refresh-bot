"""Reconstruct HTML formatting from plain text vacancy descriptions.

The BrightStaffing API strips HTML tags when returning vacancy descriptions
but the UI stores and renders HTML. This module detects formatting patterns
in the plain text and reconstructs appropriate HTML so duplicated vacancies
preserve the original formatting.

Patterns detected:
- Bullet points: sentences joined without space after period (.NextSentence)
- Section headers: short lines ending with ':' or '?' that precede content
- Paragraphs: text separated by double newlines
- Existing &nbsp; entities are preserved
"""

import re
from typing import Optional


def reconstruct_html(text: Optional[str]) -> Optional[str]:
    """Reconstruct HTML from plain text where API stripped HTML tags.

    Args:
        text: Plain text description from the BrightStaffing API.

    Returns:
        HTML-formatted string, or the original text if no patterns detected.
        Returns None/empty if input is None/empty.
    """
    if not text or not text.strip():
        return text

    text = text.strip()

    # If text already has HTML tags, return as-is
    if re.search(r'<(?:p|br|ul|ol|li|strong|em|div|span|h[1-6])\b', text, re.IGNORECASE):
        return text

    # Split into paragraphs (double newline)
    paragraphs = re.split(r'\n\s*\n', text)

    html_parts = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        lines = para.split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue

            is_header = _is_header(line)

            # Detect bullet-point pattern: sentences joined without space
            # after period, like "first item.Second item.Third item"
            bullet_items = re.split(r'\.(?=[A-Z])', line)

            if len(bullet_items) > 2 and not is_header:
                # This line contains multiple bullet-point items
                items_html = []
                for item in bullet_items:
                    item = item.strip()
                    if item:
                        if not item.endswith('.'):
                            item += '.'
                        items_html.append(f'<li>{item}</li>')
                if items_html:
                    html_parts.append('<ul>' + ''.join(items_html) + '</ul>')
            elif is_header:
                # Check if the rest of this header line also contains bullets
                # e.g. "Header:\nBullet1.Bullet2.Bullet3"
                html_parts.append(f'<strong>{line}</strong><br>')
            else:
                html_parts.append(f'<p>{line}</p>')

    result = ''.join(html_parts)
    return result if result else text


def _is_header(line: str) -> bool:
    """Detect if a line is likely a section header."""
    line = line.strip()
    if not line:
        return False

    # Short lines ending with colon are headers
    # e.g., "Wat je doet:", "Jouw profiel:", "Ons aanbod"
    if len(line) < 60 and line.endswith(':'):
        return True

    # Short lines ending with '?' that don't have periods
    # e.g., "Klaar om erin te vliegen?"
    if len(line) < 60 and line.endswith('?') and '.' not in line[:-1]:
        return True

    # Very short title-like lines (no periods, no commas, starts uppercase)
    if (len(line) < 40
            and '.' not in line
            and ',' not in line
            and line[0].isupper()):
        return True

    return False
